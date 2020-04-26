import dataclasses
import json
import os
from pathlib import Path

from flask import (Response, abort, current_app, render_template, request,
                   url_for)
from itsdangerous import URLSafeTimedSerializer
from werkzeug.local import LocalProxy

from ref import refbp
from ref.core import grading_assistant_required

log = LocalProxy(lambda: current_app.logger)

@dataclasses.dataclass
class PathSignatureToken():
    #Path prefix a request is allowed to access
    path_prefix: str

def _get_file_list(dir_path, base_dir_path, list_hidden_files=False):
    files = []
    base_dir_path = base_dir_path.rstrip('/')

    # Append previous folder if dir_path is not the base_dir_path
    if dir_path.strip('/') != base_dir_path.strip('/'):
        relative_path = str(os.path.join(dir_path, '..')).replace(base_dir_path, '')
        files.append({
            'path': relative_path,
            'is_file': False
        })

    # Iterate over all files and folders in the current dir_path
    for path in Path(dir_path).glob('*'):
        is_file = path.is_file()
        relative_path = str(path).replace(base_dir_path, '')
        files.append({
            'path': relative_path,
            'is_file': is_file
        })

    if not list_hidden_files:
        files = [f for f in files if not Path(f['path']).parts[-1].startswith('.') or f['path'].endswith('..')]

    return files


@refbp.context_processor
def file_browser_processor():
    def sign_path(path):
        token = PathSignatureToken(path)
        signer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='file-browser')
        token = signer.dumps(dataclasses.asdict(token))
        return token

    def list_dir(path):
        return _get_file_list(path, path)

    return dict(
        file_browser_sign_path=sign_path,
        file_browser_ls=list_dir
    )

@refbp.route('/admin/file-browser/load-file', methods = ['POST'])
@grading_assistant_required
def file_browser_load_file():
    data = request.values

    #The requested file path
    path = data.get('path', None)
    #A token that proves the authenticity of the request
    token = data.get('token', None)
    hide_hidden_files = data.get('hide_hidden_files', None)

    if path is None or token is None or hide_hidden_files is None:
        return abort(400)

    hide_hidden_files = hide_hidden_files == 'true'

    #Check the signature
    signer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='file-browser')
    try:
        token = signer.loads(token, max_age=8*24*60)
        token = PathSignatureToken(**token)
    except:
        log.warning(f'Invalid token: {token}', exc_info=True)
        return abort(400)

    #The allowed path prefix for this request
    path_prefix = Path(token.path_prefix)
    log.info(f'Signed prefix is {path_prefix}')
    assert path_prefix.is_absolute()

    #Just concat the signed prefix and the user requested path.
    final_path = path_prefix.joinpath(path.lstrip('/'))
    log.info(f'Trying to load file {final_path}')

    final_path = final_path.expanduser().resolve()
    assert final_path.is_absolute()

    #Check if the path is covered by the provided signature.
    if not final_path.as_posix().startswith(path_prefix.as_posix()):
        log.warning(f'Given path ({final_path}) points outside of the signed prefix ({path_prefix})')
        return abort(400)

    response = None
    if final_path.is_file():
        # If the current path belongs to a file, return the file content.
        content = None
        try:
            with open(final_path, 'r') as f:
                content = f.read()
        except Exception as e:
            return Response('Error while reading file: {e}', status=400)

        file_extension = final_path.suffix

        response = {
            'type': 'file',
            'content': content,
            'extension': file_extension
        }

    elif Path(final_path).is_dir():
        # If the current path belongs to a directory, determine all files in it
        files = _get_file_list(final_path.as_posix(), path_prefix.as_posix(), list_hidden_files=not hide_hidden_files)
        file_load_url = url_for('ref.file_browser_load_file')

        response = {
            'type': 'dir',
            'content': render_template('file_browser/file_tree.html', files=files, file_load_url=file_load_url)
        }

    else:
        return Response('', status=400)

    return Response(json.dumps(response), mimetype='application/json')


@refbp.route('/admin/file-browser/save-file', methods = ['POST'])
@grading_assistant_required
def file_browser_save_file():
    rendered_alert = render_template('file_browser/alert.html', error_message='Saving is currently not supported!')
    return Response(rendered_alert, status=500)

    # # Get filename and content from payload
    # payload = request.values
    # path = payload.get('path', None)
    # content = payload.get('content', None)
    # token = payload.get('token', None)

    # if path is None or content is None or token is None:
    #     abort(400)

    # #Check the signature
    # signer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='file-browser')
    # try:
    #     token = signer.loads(token, max_age=8*24*60)
    # except:
    #     log.warning(f'Invalid token: {token}', exc_info=True)
    #     return abort(400)

    # #We signed this, so we do not have to check whether the keys exist

    # #The allowed path prefix for this request
    # path_prefix = Path(token['path_prefix'])
    # log.info(f'Signed prefix is {path_prefix}')
    # assert path_prefix.is_absolute()

    # #Just concat the signed prefix and the user requested path.
    # final_path = path_prefix.joinpath(path.lstrip('/'))
    # log.info(f'Trying to load file {final_path}')

    # try:
    #     final_path = final_path.expanduser().resolve()
    #     assert final_path.as_posix().startswith(path_prefix.as_posix())
    # except:
    #     log.warning(f'Error while resolving path {final_path}')
    #     return abort(400)

    # if final_path.is_file():
    #     try:
    #         # Write content to file if file exists
    #         with open(final_path.as_posix(), 'w') as f:
    #             f.write(content)
    #     except Exception as e:
    #         log.warning('Failed to save file', exc_info=True)
    #         rendered_alert = render_template('file_browser/alert.html', error_message=str(e))
    #         return Response(rendered_alert, status=500)

    # else:
    #     return Response('', status=400)

    # return Response(content, mimetype='text/plain')
