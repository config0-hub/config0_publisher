#!/usr/bin/env python

def get_tf_install(**kwargs):

    '''
    https://github.com/opentofu/opentofu/releases/download/v1.6.2/tofu_1.6.2_linux_amd64.zip
    '''

    runtime_env = kwargs["runtime_env"]  # codebuild or lambda
    binary = kwargs["tf_binary"]
    version = kwargs["tf_version"]
    dl_subdir = kwargs["dl_subdir"]
    bucket_path = kwargs["tf_bucket_path"]
    arch = kwargs["arch"]
    path_dir = kwargs["tf_path_dir"]

    if runtime_env == "codebuild":
        cmds = [
          'which zip || apt-get update',
          'which zip || apt-get install -y unzip zip',
        ]
    else:
        cmds = [f'echo "downloading {binary}_{version}"']

    bucket_install = f'([ ! -f "$TMPDIR/{dl_subdir}/{binary}_{version}" ] && aws s3 cp {bucket_path} $TMPDIR/{dl_subdir}/{binary}_{version} --quiet )'
    terraform_direct = f'(cd $TMPDIR/{dl_subdir} && curl -L -s https://releases.hashicorp.com/terraform/{version}/{binary}_{version}_{arch}.zip -o {binary}_{version} && aws s3 cp {binary}_{version} {bucket_path} --quiet)'
    tofu_direct = f'cd $TMPDIR/{dl_subdir} && curl -L -s https://github.com/opentofu/opentofu/releases/download/v{version}/{binary}_{version}_{arch}.zip -o {binary}_{version} && aws s3 cp {binary}_{version} {bucket_path} --quiet'

    if binary == "terraform":
        _install_cmd = f'{bucket_install} || (echo "terraform/tofu not found in local s3 bucket" && {terraform_direct})'
    else:  # opentofu
        _install_cmd = f'{bucket_install} || (echo "terraform/tofu not found in local s3 bucket" && {tofu_direct})'

    cmds.append(_install_cmd)

    cmds.extend([
        f'mkdir -p {path_dir} || echo "trouble making path_dir {path_dir}"',
        f'(cd $TMPDIR/{dl_subdir} && unzip {binary}_{version} && mv {binary} {path_dir}/{binary} > /dev/null) || exit 0',
        f'chmod 777 {path_dir}/{binary}'])

    return cmds
