#!/usr/bin/env python

def get_tf_install(**kwargs):

    '''
    https://github.com/opentofu/opentofu/releases/download/v1.6.2/tofu_1.6.2_linux_amd64.zip
    '''

    binary = kwargs["binary"]
    version = kwargs["version"]
    bucket_path = kwargs["tf_bucket_path"]
    arch = kwargs["arch"]
    bin_dir = kwargs["bin_dir"]

    _bucket_install_1 = f'aws s3 cp {bucket_path} $TMPDIR/{binary}_{version} --quiet'
    _bucket_install_2 = f'echo "# GOT {binary} from s3/cache"'
    bucket_install = f'{_bucket_install_1} && {_bucket_install_2}'

    _terraform_direct_1 = f'echo "# Getting {binary}_{version} FROM SOURCE"'
    _terraform_direct_2 = f'cd $TMPDIR && curl -L -s https://releases.hashicorp.com/terraform/{version}/{binary}_{version}_{arch}.zip -o {binary}_{version}'
    _terraform_direct_3 = f'aws s3 cp {binary}_{version} {bucket_path} --quiet'
    terraform_direct = f'{_terraform_direct_1} && {_terraform_direct_2} && {_terraform_direct_3}'
    _tofu_direct_2 = f'cd $TMPDIR && curl -L -s https://github.com/opentofu/opentofu/releases/download/v{version}/{binary}_{version}_{arch}.zip -o {binary}_{version}'
    tofu_direct = f'{_terraform_direct_1} && {_tofu_direct_2} && {_terraform_direct_3}'

    if binary == "terraform":
        _install_cmd = f'({bucket_install} )|| (echo "terraform/tofu not found in local s3 bucket" && {terraform_direct})'
    else:  # opentofu
        _install_cmd = f'({bucket_install}) || (echo "terraform/tofu not found in local s3 bucket" && {tofu_direct})'

    cmds = [ {f"install {binary}" : _install_cmd }]

    cmds.extend([
        {"mkdir bin dir": f'mkdir -p {bin_dir} || echo "trouble making bin_dir {bin_dir}"'},
        {f"move {binary}_{version} to bin": f'(cd $TMPDIR && unzip {binary}_{version} && mv {binary} {bin_dir}/{binary} > /dev/null) || exit 0'},
        {f"chmod {binary}": f'chmod 777 {bin_dir}/{binary}'}])

    return cmds
