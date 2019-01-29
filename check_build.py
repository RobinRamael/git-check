#!/Users/robin/.virtualenvs/jenkins-check-build/bin/python

import os

import click
import git
from jenkinsapi.jenkins import Jenkins as _Jenkins


class Jenkins(object):
    def __init__(self, url, job_names):
        self.instance = _Jenkins(url)
        self.job_names = job_names

    def get_jobs(self):
        for job_name in self.job_names:
            yield self.instance.get_job(job_name)

    def get_builds(self, full_sha):
        for job in self.get_jobs():

            build_ids = job.get_buildnumber_for_revision(full_sha)

            for build_id in build_ids:
                build = job.get_build(build_id)
                yield Build(build, full_sha)


class Build(object):
    def __init__(self, build, sha):
        self.build = build
        self._status = None
        self.sha = sha

    def get_failed_tests(self):
        resultset = self.build.get_resultset()

        for test_name, result in resultset.items():
            if result.status not in ("PASSED", "SKIPPED", "FIXED"):
                yield test_name, result

    @property
    def status(self):
        if not self._status:
            self._status = self.build.get_status()

        return self._status

    @property
    def succeeded(self):
        return not self.running and self.status == "SUCCESS"

    @property
    def failed(self):
        return not self.running and not self.succeeded

    @property
    def running(self):
        return self.status is None

    @property
    def status_message(self):
        if self.running:
            return "is still running"

        if self.succeeded:
            return "succeeded"

        if self.failed:
            return "failed"

    @property
    def status_color(self):
        if self.running:
            return 'blue'

        if self.succeeded:
            return 'green'

        if self.failed:
            return 'red'

    @property
    def id(self):
        return self.build.buildno

    @property
    def short_sha(self):
        return self.sha[:10]

    def __str__(self):
        return "Build {build_id} for {sha} {status_message}.".format(build_id=self.id,
                                                                     sha=self.short_sha,
                                                                     status_message=self.status_message)


@click.command()
@click.argument("commit_ref", required=False)
@click.option("-v", "--verbose", count=True)
@click.option("-u", "--jenkins-url", default="http://jenkins.maykin.nl/")
@click.option("-j", "--jobs", multiple=True)
@click.option("-s", "--trace", default=False, is_flag=True)
def main(commit_ref=None, jenkins_url=None, jobs=None, verbose=0, trace=False):

    repo = git.Repo(os.getcwd())

    try:
        full_sha = repo.commit(commit_ref).hexsha
    except git.BadName:
        click.echo("No commit found with that name")
        exit(1)

    jenkins = Jenkins(jenkins_url, jobs)

    if verbose:
        click.echo("Connected to jenkins on {}".format(jenkins_url), err=True)

    for build in jenkins.get_builds(full_sha):
        click.echo(click.style(str(build), fg=build.status_color), err=True)

        if build.failed:
            for test, result in build.get_failed_tests():
                click.echo(test)
                if trace:
                    click.echo(result.errorStackTrace)
            break


if __name__ == "__main__":
    main(auto_envvar_prefix="JENKINS")
