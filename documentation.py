import os
from typing import Container
import yaml
import argparse
import datetime
import markdown
import xml.etree.ElementTree as ET
from github import Github

DEFAULT_OWNERS = []

DEFAULT_REVIEW_DAYS = 90
DEFAULT_REVIEW_REQUEST_LABELS = ["documentation"]

DEFAULT_REVIEW_REQUEST_BODY = """\
### Reason

{reason}

### Documentation File

```
{file}
```

### How do we resolve this?

Please add the following labels or update your documentation to reflect new changes.

+cc {default_owners}
"""

parser = argparse.ArgumentParser("documentation-tracker-action")

parser.add_argument("-i", "--working-directory", default=os.getcwd(), type=str)
parser.add_argument("-p", "--paths", action="append")
parser.add_argument("--file-types", default=["md"], action="append")
parser.add_argument("--ignore-readme", action="store_false")
# Defaults for
parser.add_argument("-o", "--default-owners", action="append")
parser.add_argument(
    "-l", "--default-labels", default=DEFAULT_REVIEW_REQUEST_LABELS, action="append"
)
# Review
parser.add_argument("--review-days", default=DEFAULT_REVIEW_DAYS)
# GitHub arguments
parser.add_argument("--github-token", default=os.environ.get("GITHUB_TOKEN"))
parser.add_argument("--github-repository", default=os.environ.get("GITHUB_REPOSITORY"))
parser.add_argument("--workflow-event", default=os.environ.get("GITHUB_EVENT_NAME"))

arguments = parser.parse_args()

if not arguments.github_token:
    raise Exception("Github Access Token required")
if not arguments.github_repository:
    raise Exception("Github Repository required")


errors = []
github = Github(arguments.github_token)
repo = github.get_repo(arguments.github_repository)


class Octokit:
    @staticmethod
    def info(msg):
        print(msg)

    def debug(msg):
        print("::debug :: {msg}".format(msg=msg))

    @staticmethod
    def warning(msg):
        print("::warning :: {msg}".format(msg=msg))

    @staticmethod
    def error(msg, file=None):
        errors.append(msg)
        if file:
            print("::error file={file},line=0,col=0::{msg}".format(msg=msg, file=file))
        else:
            print("::error ::{msg}".format(msg=msg))


def findFiles(root: str, file_types: list, ingore_readme: bool = True) -> list:
    Octokit.debug("Finding files - " + root)
    paths = []
    for directory, _, files in os.walk(root):
        for file in files:
            _, ext = os.path.splitext(file)
            if ext.replace(".", "") not in file_types:
                continue
            if ingore_readme and file == "README.md":
                continue
            paths.append(os.path.join(directory, file))
    return paths


def findMetaDataInFile(path: str):
    Octokit.debug("Finding metadata in file - " + path)

    with open(path, "r") as handle:
        data = handle.read()

    # HACK: the python `markdown` module doesn't like `---`
    if data.startswith("---"):
        data = data.replace("---", "```yaml", 1)
        data = data.replace("---", "```", 1)

    markdown_data = markdown.markdown(
        data, output_format="html5", extensions=["fenced_code"]
    )

    markdown_data = "<div>" + markdown_data + "</div>"
    # TODO: Another hack to support commented config block
    markdown_data = markdown_data.replace("<!--", "")
    markdown_data = markdown_data.replace("-->", "")

    root = ET.fromstring(markdown_data)
    # Find metadata block
    block = root.find("./pre/code[@class='language-yaml']")

    if block is None or str(block) == "None":
        return

    return yaml.safe_load(block.text)


def metadataChecking(metadata: dict, filepath: str):
    Octokit.debug("Validating and Checking metadata")

    # Checks: required variables
    if metadata.get("name") is None:
        Octokit.error("Variable missing - name")
    # TODO: Version check?
    if metadata.get("datetime") is None:
        Octokit.error("Variable missing - datetime")
    if metadata.get("datetime", {}).get("publish") is None:
        Octokit.error("Variable missing - datetime")
    if metadata.get("owners") is None:
        Octokit.error("Variable missing - owners")

    now = datetime.datetime.now()
    deadline = datetime.timedelta(days=arguments.review_days)

    try:
        if metadata.get("datetime", {}).get("updated"):
            # Checks: Datetime checking (updated)
            updated_date = datetime.datetime.strptime(
                metadata.get("datetime", {}).get("updated"), "%Y/%m/%d"
            )

            if (deadline + updated_date) < now:
                createReviewRequest(
                    "Documentation might be outdated (+90 days)",
                    name=metadata.get("name"),
                    filepath=filepath,
                    owners=metadata.get("owners", arguments.default_owners),
                )

        else:
            # Checks: Datetime checking (creation)
            publishing_date = datetime.datetime.strptime(
                metadata.get("datetime", {}).get("publish"), "%Y/%m/%d"
            )

            if (deadline + publishing_date) < now:
                createReviewRequest(
                    "Documentation might be outdated (+90 days)",
                    name=metadata.get("name"),
                    filepath=filepath,
                    owners=metadata.get("owners", arguments.default_owners),
                )

    except ValueError as err:
        Octokit.error("Timestamp is not correct, please follow documentation")

    return True


def createReviewRequest(msg, name, filepath, owners=[]):
    Octokit.error(msg)

    title = "Docs: Review Request - " + name
    issue_exists = True

    for issue in repo.get_issues(state="open"):
        if issue.title == title:
            issue_exists = issue
            break

    if issue_exists is True:
        Octokit.info("Creating documentation issue")
        body = DEFAULT_REVIEW_REQUEST_BODY.format(
            file=filepath,
            default_owners=", ".join(["@" + o for o in arguments.default_owners]),
            reason=msg,
        )

        labels = [repo.get_label(lbl) for lbl in arguments.default_labels]

        # TODO: support for multiple assignees isn't supported
        repo.create_issue(
            title=title,
            body=body,
            labels=labels,
            assignee=owners[0],
        )

    else:
        print("Skipping the issue creation, checking other data")

        # TODO: Check if the issue has been open for X days


if __name__ == "__main__":
    files = []
    paths = arguments.paths
    if not arguments.paths:
        paths = os.listdir(arguments.working_directory)

    for path in paths:
        full_path = os.path.join(arguments.working_directory, path)

        if not os.path.isdir(full_path):
            continue

        if os.path.exists(full_path):
            files = findFiles(full_path, arguments.file_types, arguments.ignore_readme)

    for markdown_file in files:
        Octokit.info("Processing :: " + markdown_file)

        metadata = findMetaDataInFile(markdown_file)

        if metadata is None:
            Octokit.error("No metadata present in file", markdown_file)
            continue

        metadataChecking(
            metadata, markdown_file.replace(arguments.working_directory + "/", "")
        )

    # Only break the workflow if errors are present and pull_request event type
    if errors and arguments.workflow_event == "pull_request":
        raise Exception("Errors present")

    Octokit.info("Successfully analysed files")