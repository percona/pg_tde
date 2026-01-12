# Documentation contributing guide

Thank you for deciding to contribute and help us improve the **pg_tde documentation**!

We welcome contributors from all users and community. By contributing, you agree to the [Percona Community code of conduct](https://github.com/percona/community/blob/main/content/contribute/coc.md).

If you want to contribute code, see the [Code contribution guide](../CONTRIBUTING.md).

You can contribute to the documentation in one of the following ways:

1. [Submit a pull request (PR) for documentation on Github](#edit-documentation-on-github)
2. Reach us on our [Forums](https://forums.percona.com/c/postgresql/pg-tde-transparent-data-encryption-tde/82)

The `pg_tde` documentation is written in Markdown.

## Edit documentation on GitHub

1. Click the **Edit this page** icon next to the page title. The source `.md` file of the page opens in GitHub editor in your browser. If you haven’t worked with the repository before, GitHub creates a [fork](https://docs.github.com/en/github/getting-started-with-github/fork-a-repo) of it for you.

2. Edit the page. You can check your changes on the **Preview** tab.

3. Commit your changes:
    * Describe the changes you have made
    * Select the **Create a new branch for this commit** and name your branch
    * Click **Propose changes** to create the pull request

4. GitHub creates a branch and a commit for your changes. It loads a new page on which you can open a pull request to Percona. The page shows the base branch (the one you offer your changes for) your commit message and a diff (a visual representation of your changes against the original page). This allows you to make a last-minute review. When you are ready, click the **Create pull request** button.

5. Your changes will be reviewed and merged into the documentation.

### Edit documentation locally

To edit the documentation locally:

1. Fork this repository
2. Clone the repository on your machine:

```sh
git clone --recursive git@github.com:<your-name>/postgres.git
```

3. Change the directory to `contrib/pg_tde` and add the remote upstream repository:

```sh
git remote add upstream git@github.com:percona/postgres.git
```

4. Pull the latest changes from upstream:

```sh
git fetch upstream
git merge upstream
```

5. Create a separate branch for your changes. If you work on a Jira issue, please follow this pattern for a branch name: `<PG-123>-short-description`:

```sh
git checkout -b <PG-123>-short-description upstream/<target-branch>

```

6. Make changes
7. Commit your changes
8. Open a pull request to Percona

#### Build the documentation

To verify how your changes look, you can generate a static site locally:

- [Use Docker](#use-docker)
- [Install MkDocs and build locally](#install-mkdocs-and-build-locally)

##### Use Docker

1. [Get Docker](https://docs.docker.com/get-docker/)
2. We use [our Docker image](https://hub.docker.com/repository/docker/perconalab/pmm-doc-md) to build documentation. Run the following command:

```sh
cd contrib/pg_tde/documentation
docker run --rm -v $(pwd):/docs perconalab/pmm-doc-md mkdocs build
```

   If Docker can't find the image locally, it first downloads the image, and then runs it to build the documentation.

3. Go to the ``site`` directory and open the ``index.html`` file to see the documentation.

If you want to see the changes as you edit the docs, use this command instead:

```sh
cd contrib/pg_tde/documentation
docker run --rm -v $(pwd):/docs -p 8000:8000 perconalab/pmm-doc-md mkdocs serve --dev-addr=0.0.0.0:8000
```

Wait until you see `INFO    -  Start detecting changes`, then enter `0.0.0.0:8000` in the browser's address bar. The documentation automatically reloads after you save the changes in source files.

##### Install MkDocs and build locally

1. Install [Python]

2. Install MkDocs and required extensions:

    ```sh
    pip install -r requirements.txt
    ```

3. Build the site:

    ```sh
    cd contrib/pg_tde/documentation
    mkdocs build
    ```

4. Open `site/index.html`

Or, to run the built-in web server:

```sh
cd contrib/pg_tde/documentation
mkdocs serve
```

View the site at <http://127.0.0.1:8000>

#### Build PDF file

To build a PDF version of the documentation, do the following:

1. Disable displaying the last modification of the page:

    ```sh
    export ENABLED_GIT_REVISION_DATE=false
    ```

2. Build the PDF file:

    ```sh
    ENABLE_PDF_EXPORT=1 mkdocs build -f mkdocs-pdf.yml
    ``` 

    The PDF document is in the ``contrib/pg_tde/documentation/site/pdf`` folder.

[MkDocs]: https://www.mkdocs.org/
[Markdown]: https://daringfireball.net/projects/markdown/
[Git]: https://git-scm.com
[Python]: https://www.python.org/downloads/
[Docker]: https://docs.docker.com/get-docker/