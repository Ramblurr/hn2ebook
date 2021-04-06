import subprocess


def _run(command):
    try:
        p = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True
        )
    except OSError as e:
        msg_format = "Problem running password command %s (%s)."
        msg = msg_format % (command, e)
        raise Exception(msg)

    stdout, stderr = p.communicate()
    return stdout, stderr, p


def _check_results(command, stdout, stderr, popen):
    if popen.returncode != 0:
        raise Exception(
            "Password command %s returned non-zero (%s) when getting secret: %s"
            % (command, popen.returncode, stderr)
        )


def get_password(command):
    stdout, stderr, p = _run(command)
    _check_results(command, stdout, stderr, p)

    password = stdout.strip(b"\r\n")

    if not password:
        raise Exception("Invalid password returned from script (%s)" % command)

    return password
