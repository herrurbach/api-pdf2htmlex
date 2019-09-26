'''
@Version: 0.0.1a
@Author: ider, tomate
@LastEditors: ider
@Description: pdf2htmlEX API
'''

import os
import time
import zipfile
import tempfile
import uuid
import shutil
import subprocess
import json
import datetime
from flask import Flask, request, send_from_directory, send_file
from werkzeug.utils import secure_filename
from concurrent.futures import ThreadPoolExecutor
import requests
from file_compress import compress

app = Flask(__name__)

TIMEOUT = int(os.environ.get('TIMEOUT', 60*60*24))
POOL_SIZE = os.environ.get('POOL_SIZE', 1)
# chrome 提前转换 pdf
PDF2PDF = os.environ.get('PDF2PDF')
# 是否转换压缩 png 图片，html, 默认 是
WEBP_FLAG = os.environ.get('WEBP', True)

UPLOAD_FOLDER = '/tmp'
bin = "/usr/local/bin/pdf2htmlEX"
ALLOWED_EXTENSIONS = set(['pdf'])


app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['COUNT'] = 0
app.config['executor_worker'] = ThreadPoolExecutor(max_workers=int(POOL_SIZE))

app.config['executor_file'] = ThreadPoolExecutor(max_workers=5)

app.config['SESSION_TYPE'] = 'filesystem'
app.config['SECRET_KEY'] = os.urandom(24)
app.config['COUNT'] = 0


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/pdf2htmlEX', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files or 'command' not in request.form:
            return "no file", 404
        file = request.files['file']
        command = request.form['command']
        if file.filename == '':
            return "no filename", 404

        if file and allowed_file(file.filename):
            filename = file.filename
            pdf_folder_uuid = str(uuid.uuid4())
            pdf_floder_path = os.path.join(app.config['UPLOAD_FOLDER'], pdf_folder_uuid)
            pdf_path = os.path.join(pdf_floder_path, filename)
            os.mkdir(pdf_floder_path)
            file.save(pdf_path)
            if PDF2PDF:
                pdf2pdf(pdf_path)
            try:
                fp = pdf2htmlEX(pdf_path, json.loads(command))
                app.config['executor_file'].submit(shutil.rmtree, pdf_floder_path)
            except Exception as e:
                app.config['executor_file'].submit(shutil.rmtree, pdf_floder_path)
                return str(e), 500
            remove_old_fold(app.config['UPLOAD_FOLDER'])
            app.config['COUNT'] += 1
            return send_file(fp, as_attachment=True, attachment_filename=filename.split('.')[0] + '.zip')
            # return "ok" + command, 200
    elif request.method == 'GET':
        return 'Completing ' + app.config['COUNT'] + ' document conversions'
    return "unknow error", 500


def pdf2pdf(pdf2_path):
    files = {'file': open(pdf2_path, 'rb')}
    req = requests.post(PDF2PDF, files=files)
    # 转换超时
    if req.status_code == 403:
        return False
    elif req.status_code != 200:
        print(req.text)
        return False
    with open(pdf2_path, 'wb')as f:
        f.write(req.content)
    return True


def pdf2htmlEX(pdf_path, command):
    out_folder_uuid = str(uuid.uuid4())
    folder_path = os.path.join(app.config['UPLOAD_FOLDER'], out_folder_uuid)
    os.mkdir(folder_path)
    cmd = [bin]
    if command:
        cmd.extend(command.split(' '))

    cmd.extend(['--dest-dir', folder_path, pdf_path])

    # 只有一个的队列
    # if os.path.getsize(pdf_path) > 2 * 1024 * 1024:
    #     ret = app.config['executor_large'].submit(subprocess.check_output, cmd)
    # else:
    #     ret = app.config['executor_large'].submit(subprocess.check_output, cmd)
    ret = app.config['executor_worker'].submit(subprocess.check_output, cmd, timeout=TIMEOUT)
    ret.result()

    # subprocess.check_output(cmd)
    # shutil.copy(pdf_path,os.path.join(pdf_path,folder_path))

    fp = tempfile.TemporaryFile()
    with zipfile.ZipFile(fp, 'w') as myzip:
        for obj in os.walk(folder_path):
            for file_name in obj[2]:

                file_path = obj[0] + os.sep + file_name
                #  png 过滤
                if file_name.endswith('.png') and os.path.getsize(file_path) < 10 * 1024:
                    continue
                if WEBP_FLAG:
                    file_path = compress(file_path)
                myzip.write(file_path, arcname=file_path.replace(folder_path,'').lstrip('/'))
    app.config['executor_file'].submit(shutil.rmtree, folder_path)
    fp.seek(0)
    return fp

def remove_old_fold(root_path):
    for fold in os.listdir(root_path):
        fold_path = os.path.join(root_path,fold)
        if os.path.isdir(fold_path):
            date = datetime.datetime.fromtimestamp(os.path.getmtime(fold_path))
            now = datetime.datetime.now()
            if (now - date).seconds > 32 * 60 *60:
                app.config['executor_file'].submit(shutil.rmtree, fold_path)


if __name__ == '__main__':
    app.run(debug=True,host="0.0.0.0",port=5000)
