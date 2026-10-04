import os, tempfile, sys
print('TEMP=', os.environ.get('TEMP'))
print('TMP=', os.environ.get('TMP'))
for label, candidate in (('default', None), ('repo tmp', r'D:\ai_develop_project_space\doc-tool\tmp'),
                         ('user home', os.path.expanduser('~'))):
    if candidate:
        os.environ['TEMP'] = candidate; os.environ['TMP'] = candidate
        tempfile.tempdir = None
    try:
        fd, path = tempfile.mkstemp(prefix='probe-')
        os.close(fd); os.unlink(path)
        print(label, 'mkstemp OK')
    except Exception as exc:
        print(label, 'mkstemp FAIL', type(exc).__name__, str(exc)[:90])