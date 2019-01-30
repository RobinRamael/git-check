#!/Users/robin/.virtualenvs/jenkins-check-build/bin/python

import os
import json
from collections import defaultdict

import click
import git
from jenkinsapi.jenkins import Jenkins as _Jenkins


class Jenkins(object):
    def __init__(self, url, job_names, cache_path=None):
        self.client = _Jenkins(url)
        self.job_names = job_names

        self.builds = {}

        if cache_path and os.path.exists(cache_path):
            self.load_cache(cache_path)

    def load_cache(self, cache_path):
        with open(cache_path) as fp:
            data = json.load(fp)

        cache = defaultdict(list)

        for build_data in data["builds"]:
            cache[build_data["job_name"], build_data["sha"]].append(Build.from_dict(build_data))

        self.builds = dict(cache)

    def save_cache(self, cache_path):
        build_data = []

        for builds in self.builds.values():
            for build in builds:
                build_data.append(build.to_dict())

        data = {'builds': build_data}

        with open(cache_path, 'w') as fp:
            json.dump(data, fp)

    def get_builds(self, full_sha):
        for job_name in self.job_names:
            for build in self.get_job_builds(job_name, full_sha):
                yield build

    def fetch_builds(self, job_name, sha):
        job = self.client.get_job(job_name)

        build_ids = job.get_buildnumber_for_revision(sha)

        return [
            Build.from_jenkins(job_name, sha, job.get_build(build_id)) for build_id in build_ids
        ]

    def get_job_builds(self, job_name, full_sha):
        try:
            return self.builds[job_name, full_sha]
        except KeyError:
            builds = self.fetch_builds(job_name, full_sha)
            self.builds[job_name, full_sha] = [b for b in builds if not b.running]
            return builds


class TestResult(object):
    def __init__(self, name, status, trace):
        self.name = name
        self.status = status
        self.trace = trace

    @classmethod
    def from_jenkins(cls, name, result):
        return cls(name, result.status, result.errorStackTrace)

    @classmethod
    def from_dict(cls, data):
        return cls(data["name"], data["status"], data["trace"])

    def to_dict(self):
        return {
            'name': self.name,
            'status': self.status,
            'trace': self.trace
        }

    @property
    def failed(self):
        return self.status not in ("PASSED", "SKIPPED", "FIXED")


class Build(object):
    def __init__(self, job_name, build_id, sha, status, tests):
        self.job_name = job_name
        self.id = build_id
        self.sha = sha
        self.status = status
        self.tests = tests

    @classmethod
    def from_jenkins(cls, job_name, sha, build_obj):

        tests = {
            name: TestResult.from_jenkins(name, result)
            for name, result in build_obj.get_resultset().items()
        }

        return cls(job_name, build_obj.buildno, sha, build_obj.get_status(), tests)

    @classmethod
    def from_dict(cls, data):
        tests = {test_data['name']: TestResult.from_dict(test_data) for test_data in data["tests"]}

        return cls(data["job_name"], data["id"], data["sha"], data["status"], tests)

    def to_dict(self):
        tests_data = [testresult.to_dict() for testresult in self.tests.values()]

        return {
            'job_name': self.job_name,
            'id': self.id,
            'sha': self.sha,
            'status': self.status,
            'tests': tests_data
        }

    def get_failed_tests(self):
        return [test for name, test in self.tests.items() if test.failed]

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
            return "blue"

        if self.succeeded:
            return "green"

        if self.failed:
            return "red"

    @property
    def short_sha(self):
        return self.sha[:10]

    def __str__(self):
        return "Build {build_id} for {sha} {status_message}.".format(
            build_id=self.id, sha=self.short_sha, status_message=self.status_message
        )


@click.command()
@click.argument("commit_ref", required=False)
@click.option("-v", "--verbose", count=True)
@click.option("-u", "--jenkins-url", default="http://jenkins.maykin.nl/")
@click.option("-j", "--jobs", multiple=True)
@click.option("-s", "--trace", default=False, is_flag=True)
def main(commit_ref=None, jenkins_url=None, jobs=None, verbose=0, trace=False):

    repo = git.Repo(os.getcwd(), search_parent_directories=True)

    cache_path = os.path.join(repo.working_tree_dir, ".builds_cache.json")

    try:
        full_sha = repo.commit(commit_ref).hexsha
    except git.BadName:
        click.echo("No commit found with that name")
        exit(1)

    jenkins = Jenkins(jenkins_url, jobs, cache_path)

    if verbose:
        click.echo("Connected to jenkins on {}".format(jenkins_url), err=True)

    for build in jenkins.get_builds(full_sha):
        click.echo(click.style(str(build), fg=build.status_color), err=True)

        if build.failed:
            for test in build.get_failed_tests():
                click.echo(test.name)
                if trace:
                    click.echo(test.trace)

        if not build.running:
            break

    jenkins.save_cache(cache_path)


if __name__ == "__main__":
    main(auto_envvar_prefix="JENKINS")
