#
# Copyright 2019 XEBIALABS
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#

import re, requests, sys, traceback
import java.lang.String as String
from com.xebialabs.overthere import CmdLine
from com.xebialabs.overthere.util import CapturingOverthereExecutionOutputHandler, OverthereUtils
from com.xebialabs.overthere.local import LocalConnection


class PluginClient(object):
    def __init__(self):
        self.unix=True

    @staticmethod
    def get_headers(api_token):
        return {
            'Accept' : 'application/vnd.github.v3+json',
            'Authorization' : 'token %s' % api_token,
            'Content-Type' : 'application/json'
        }

    @staticmethod
    def get_client():
        return PluginClient()

    def open_url(self, method, url, headers=None, data=None, json_data=None):
        if headers is None:
            headers = self.headers
        return requests.request('%s' % method, url, data=data, json=json_data, headers=headers, verify=False)

    def get_response_for_endpoint(self, method, url, endpoint, error_message, object_id=None, json_data=None, data=None, headers=None):
        full_endpoint_url = "%s/%s" % (url, endpoint)
        print "full_endpoint_url : %s" % full_endpoint_url
        if object_id is not None and object_id:
            full_endpoint_url = "%s/%s" % (full_endpoint_url, object_id)
        response = self.open_url(method, full_endpoint_url, headers=headers, json_data=json_data, data=data)
        if not response.ok:
            raise Exception("%s Status Code:[%s] Content: [%s]" % (error_message, response.status_code, response.text))
        return response.text

    def plugin_creategithubrepository(self, variables):
        repo_data = '{"name":"%s","private":false}' % variables['github_repo_name']
        if variables['create_in_github_organization']:
            endpoint = 'orgs/%s/repos' % variables['github_organization']
        else:
            endpoint = 'user/repos'
        return self.get_response_for_endpoint(
            'POST',
            'https://api.github.com',
            endpoint,
            'Failed to create repository [%s].' % variables['github_repo_name'],
            headers=PluginClient.get_headers(variables['github_api_token']),
            data=repo_data)

    def plugin_configuregithubrepository(self, variables):
        connection=None
        workspace_path=None
        try:
            connection = LocalConnection.getLocalConnection()
            workspace_path = PluginClient.create_tmp_workspace(connection)
            # Step 1 -- Clone the Repo
            if variables['create_in_github_organization']:
                path = variables['github_organization']
            else:
                path = variables['github_username']
            clone_cmd='#!/bin/sh\n%s clone https://github.com/%s/%s.git\n' \
                    % (variables['git_path'], path, variables['github_repo_name'])
            PluginClient.execute_command(connection, workspace_path, clone_cmd)
            # Step 2 -- Create .travis.yml file
            PluginClient.create_travis_yml_file(connection, workspace_path, variables)
            # Step 3 -- Sync Travis
            sync_cmd='#!/bin/sh\ncd %s\n%s sync\n' % (variables['github_repo_name'], variables['travis_path'])
            PluginClient.execute_command(connection, workspace_path, sync_cmd)
            # Step 4 -- Enable Project
            enable_cmd='#!/bin/sh\ncd %s\n%s enable --no-interactive\n' % (variables['github_repo_name'], variables['travis_path'])
            PluginClient.execute_command(connection, workspace_path, enable_cmd)
            # Step 5 -- Add HipChat Notifications
            if variables['integrate_with_hipchat']:
                hipchat_cmd='#!/bin/sh\ncd %s\n%s encrypt --no-interactive %s@%s --add notifications.hipchat.rooms\n' \
                        % (variables['github_repo_name'], variables['travis_path'], variables['hipchat_token'], variables['hipchat_room_id'])
                PluginClient.execute_command(connection, workspace_path, hipchat_cmd)
            # Step 6 -- Add GitHub Releases
            releases_cmd='#!/bin/sh\ncd %s\n%s encrypt --no-interactive "%s" --add deploy.api_key.secure\n' \
                    % (variables['github_repo_name'], variables['travis_path'], variables['github_api_token'])
            PluginClient.execute_command(connection, workspace_path, releases_cmd)
            # Step 7 -- Add the gradle stuff
            gradle_wrapper_cmd='#!/bin/sh\ncd %s\n%s wrapper --gradle-version %s\n' % (variables['github_repo_name'], variables['gradle_path'], variables['gradle_version'])
            PluginClient.execute_command(connection, workspace_path, gradle_wrapper_cmd)
            # settings.gradle
            PluginClient.create_settings_gradle_file(connection, workspace_path, variables)
            # build.gradle
            PluginClient.create_build_gradle_file(connection, workspace_path, variables)
            # Step 8 -- .gitignore
            PluginClient.create_gitignore_file(connection, workspace_path, variables)
            # Step 9 -- Generate README.md
            PluginClient.create_readme_file(connection, workspace_path, variables)
            # Step 10 -- Create License File
            PluginClient.create_license_file(connection, workspace_path, variables)
            # Step 11 -- Add/Commit/Push
            push_cmd='#!/bin/sh\ncd %s\n%s add -A\n%s commit -m "Initial Plugin Setup"\n%s push "https://%s:%s@github.com/%s/%s.git"' \
                    % (variables['github_repo_name'], variables['git_path'], variables['git_path'], variables['git_path'],
                        variables['github_username'], variables['github_password'], path, variables['github_repo_name'])
            PluginClient.execute_command(connection, workspace_path, push_cmd)
        except Exception:
            traceback.print_exc(file=sys.stdout)
            sys.exit(1)
        finally:
            if connection is not None and workspace_path is not None:
                self.zip_workspace(workspace_path, connection)
            if connection is not None:
                connection.close()


    @staticmethod
    def execute_command(connection, workspace_path, command):
        try:
            print "executing command: %s" % command
            script_file = connection.getFile(OverthereUtils.constructPath(connection.getFile(workspace_path), 'command.cmd'))
            OverthereUtils.write(String(command).getBytes(), script_file)
            script_file.setExecutable(True)
            command = CmdLine()
            command.addArgument(script_file.getPath())
            output_handler = CapturingOverthereExecutionOutputHandler.capturingHandler()
            error_handler = CapturingOverthereExecutionOutputHandler.capturingHandler()
            exit_code = connection.execute(output_handler, error_handler, command)
            print "exit_code : %s" % exit_code
            print "output: %s" % output_handler.getOutput()
            print "errors: %s" % error_handler.getOutput()
            return [exit_code, output_handler, error_handler]
        except Exception:
            traceback.print_exc(file=sys.stdout)
            sys.exit(1)

    @staticmethod
    def create_tmp_workspace(connection):
        try:
            tmp_workspace_file = connection.getTempFile('tmp_workspace')
            workspace_path = re.sub('tmp_workspace', '', tmp_workspace_file.getPath())
            workspace_directory = connection.getFile(workspace_path)
            connection.setWorkingDirectory(workspace_directory)
            return workspace_path
        except Exception:
            traceback.print_exc(file=sys.stdout)
            sys.exit(1)

    def zip_workspace(self, workspace_path, connection):
        zip_script = self.get_os_specific_zip_command(workspace_path)
        zip_script_file = connection.getFile(OverthereUtils.constructPath(connection.getFile(workspace_path), 'zip.cmd'))
        OverthereUtils.write(String(zip_script).getBytes(), zip_script_file)
        zip_script_file.setExecutable(True)
        command = CmdLine()
        command.addArgument(zip_script_file.getPath())
        return connection.execute(command)

    def get_os_specific_zip_command(self, workspace_path):
        if self.unix: return "#!/bin/bash\ncd %s\ntar -czf /tmp/workspace.tgz ." % workspace_path
        else: return "@echo off\r\ncd %s\r\ntar -czf C:\\Windows\\Temp\\workspace.tgz .\r\n" % workspace_path

    @staticmethod
    def create_travis_yml_file(connection, workspace_path, variables):
        contents='''language: java
sudo: false
deploy:
    provider: releases
    file: build/libs/%s-%s.jar
    skip_cleanup: true
    on:
        all_branches: true
        tags: true
        repo: %s/%s
''' % (variables['github_repo_name'], variables['initial_version'], variables['github_organization'], variables['github_repo_name'])
        repo_directory=OverthereUtils.constructPath(connection.getFile(workspace_path), '%s' % variables['github_repo_name'])
        travis_yml_file=connection.getFile(OverthereUtils.constructPath(connection.getFile(repo_directory), '.travis.yml'))
        OverthereUtils.write(String(contents).getBytes(), travis_yml_file)

    @staticmethod
    def create_settings_gradle_file(connection, workspace_path, variables):
        contents='rootProject.name=\'%s\'\n' % variables['github_repo_name']
        repo_directory=OverthereUtils.constructPath(connection.getFile(workspace_path), '%s' % variables['github_repo_name'])
        settings_gradle_file=connection.getFile(OverthereUtils.constructPath(connection.getFile(repo_directory), 'settings.gradle'))
        OverthereUtils.write(String(contents).getBytes(), settings_gradle_file)

    @staticmethod
    def create_build_gradle_file(connection, workspace_path, variables):
        contents='''plugins {
    id "com.github.hierynomus.license" version "0.13.0"
}

defaultTasks 'build'
apply plugin: 'java'
apply plugin: 'idea'
apply plugin: 'eclipse'
apply plugin: 'maven'
version='%s'

license {
    header rootProject.file('License.md')
    strictCheck false
    excludes(["**/*.json"])
    ext.year = Calendar.getInstance().get(Calendar.YEAR)
    ext.name = 'XEBIALABS'
}
''' % variables['initial_version']
        repo_directory=OverthereUtils.constructPath(connection.getFile(workspace_path), '%s' % variables['github_repo_name'])
        build_gradle_file=connection.getFile(OverthereUtils.constructPath(connection.getFile(repo_directory), 'build.gradle'))
        OverthereUtils.write(String(contents).getBytes(), build_gradle_file)

    @staticmethod
    def create_gitignore_file(connection, workspace_path, variables):
        contents='''.gradle
.idea
build
supervisord.log
supervisord.pid
'''
        repo_directory=OverthereUtils.constructPath(connection.getFile(workspace_path), '%s' % variables['github_repo_name'])
        gitignore_file=connection.getFile(OverthereUtils.constructPath(connection.getFile(repo_directory), '.gitignore'))
        OverthereUtils.write(String(contents).getBytes(), gitignore_file)

    @staticmethod
    def create_readme_file(connection, workspace_path, variables):
        if variables['create_in_github_organization']:
            path = variables['github_organization']
        else:
            path = variables['github_username']
        contents='''# %s

[![Build Status](https://travis-ci.org/%s/%s.svg?branch=master)](https://travis-ci.org/%s/%s)
[REPLACE ME WITH CODACY BADGE](https://www.codacy.com)
[![Code Climate](https://codeclimate.com/github/%s/%s/badges/gpa.svg)](https://codeclimate.com/github/%s/%s)
[![License: MIT][%s-license-image] ][%s-license-url]
[![Github All Releases][%s-downloads-image]]()

[%s-license-image]: https://img.shields.io/badge/License-MIT-yellow.svg
[%s-license-url]: https://opensource.org/licenses/MIT
[%s-downloads-image]: https://img.shields.io/github/downloads/xebialabs-community/%s/total.svg

## Preface

## Overview

## Installation

## References
''' % (variables['github_repo_name'], path, variables['github_repo_name'], path,
       variables['github_repo_name'], path, variables['github_repo_name'], path,
       variables['github_repo_name'], variables['github_repo_name'], variables['github_repo_name'], variables['github_repo_name'],
       variables['github_repo_name'], variables['github_repo_name'], variables['github_repo_name'], variables['github_repo_name'],)
        repo_directory=OverthereUtils.constructPath(connection.getFile(workspace_path), '%s' % variables['github_repo_name'])
        readme_file=connection.getFile(OverthereUtils.constructPath(connection.getFile(repo_directory), 'README.md'))
        OverthereUtils.write(String(contents).getBytes(), readme_file)

    @staticmethod
    def create_license_file(connection, workspace_path, variables):
        contents='''
Copyright ${year} ${name}

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.'''
        repo_directory=OverthereUtils.constructPath(connection.getFile(workspace_path), '%s' % variables['github_repo_name'])
        readme_file=connection.getFile(OverthereUtils.constructPath(connection.getFile(repo_directory), 'License.md'))
        OverthereUtils.write(String(contents).getBytes(), readme_file)
