$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$utf8 = New-Object System.Text.UTF8Encoding($false)
$root = Split-Path $PSScriptRoot -Parent
$release = Join-Path $root 'release'
$cache = Join-Path $release '_cache'
$name = 'APS排产-' + (Get-Date -Format 'yyyyMMdd')
$package = Join-Path $release $name
$archive = $package + '.zip'
$hostPython = (Get-Command python -CommandType Application | Select-Object -First 1).Source
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONIOENCODING = 'utf-8'
New-Item -ItemType Directory -Force -Path $cache | Out-Null

# 清理仅限本次构建的包目录，保留下载缓存和验收目录。
if ([IO.Path]::GetFullPath($package) -ne (Join-Path ([IO.Path]::GetFullPath($release)) $name)) {
    throw '包目录不在 release 下'
}
if (Test-Path -LiteralPath $package) { Remove-Item -LiteralPath $package -Recurse -Force }
if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
New-Item -ItemType Directory -Path $package | Out-Null
$pythonZip = Join-Path $cache 'python-3.12.10-embed-amd64.zip'
if (-not (Test-Path -LiteralPath $pythonZip)) {
    throw '缺少离线缓存 python-3.12.10-embed-amd64.zip'
} else {
    Write-Output 'Using cached Python 3.12.10 amd64'
}
$pythonDir = Join-Path $package 'python'
Expand-Archive -LiteralPath $pythonZip -DestinationPath $pythonDir
[IO.File]::WriteAllText((Join-Path $pythonDir 'python312._pth'), "python312.zip`r`n.`r`n..`r`nLib\site-packages`r`nimport site`r`n", $utf8)
# pip 的 HTTP 缓存不是 wheel 目录；还原其中已有的 wheel，供 --no-index 离线安装。
@'
from pathlib import Path
import shutil
import sys
import zipfile
cache = Path(sys.argv[1])
wheels = cache / 'wheels'
wheels.mkdir(exist_ok=True)
for body in (cache / 'pip' / 'http-v2').rglob('*.body'):
    if not zipfile.is_zipfile(body):
        continue
    with zipfile.ZipFile(body) as archive:
        wheel = next((n for n in archive.namelist() if n.endswith('.dist-info/WHEEL')), None)
        if wheel is None:
            continue
        distribution = wheel.split('/')[0].removesuffix('.dist-info')
        tags = [line[5:] for line in archive.read(wheel).decode().splitlines() if line.startswith('Tag: ')]
        shutil.copyfile(body, wheels / (distribution + '-' + tags[-1] + '.whl'))
print('Offline wheels: ' + str(len(list(wheels.glob('*.whl')))))
'@ | & $hostPython - $cache
if ($LASTEXITCODE -ne 0) { throw "wheel cache exit $LASTEXITCODE" }
& $hostPython -m pip --isolated install --no-index --find-links (Join-Path $cache 'wheels') --disable-pip-version-check --no-compile --target (Join-Path $pythonDir 'Lib/site-packages') --only-binary=:all: --platform win_amd64 --python-version 3.12 -r (Join-Path $PSScriptRoot 'release-requirements.txt')
if ($LASTEXITCODE -ne 0) { throw "pip exit $LASTEXITCODE" }
foreach ($dll in @('msvcp140.dll', 'msvcp140_1.dll', 'msvcp140_2.dll', 'msvcp140_atomic_wait.dll', 'msvcp140_codecvt_ids.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'concrt140.dll')) {
    if (-not (Test-Path -LiteralPath (Join-Path $pythonDir $dll))) {
        Copy-Item -LiteralPath (Join-Path "$env:SystemRoot\System32" $dll) -Destination $pythonDir
    }
}

function Copy-Tree($source, $destination, $excluded) {
    & robocopy $source $destination /E /XD __pycache__ _out @excluded /XF *.pyc /NFL /NDL /NJH /NJS /NP | Out-Host
    if ($LASTEXITCODE -ge 8) { throw "robocopy exit $LASTEXITCODE" }
}
foreach ($dir in @('engine', 'judge', 'server', 'spec', 'cases')) {
    Copy-Tree (Join-Path $root $dir) (Join-Path $package $dir) @('t30-trial')
}
# judge.selftest 固定读取的历史计划夹具（其余 _out 运行产物不进包）
$fixture = 'cases/1d-annual-feedback/_out/T-07-feedback-pass-1.plan.json'
New-Item -ItemType Directory -Force -Path (Split-Path (Join-Path $package $fixture)) | Out-Null
Copy-Item -LiteralPath (Join-Path $root $fixture) -Destination (Join-Path $package $fixture)
New-Item -ItemType Directory -Path (Join-Path $package 'tools') | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'run_case.py') -Destination (Join-Path $package 'tools')
$uiBuild = Join-Path $cache 'ui-build'
Copy-Tree (Join-Path $root 'ui') $uiBuild @('node_modules', 'dist')
if (-not (Test-Path -LiteralPath (Join-Path $uiBuild 'node_modules'))) {
    New-Item -ItemType Junction -Path (Join-Path $uiBuild 'node_modules') -Target (Join-Path $root 'ui/node_modules') | Out-Null
}
& npm --prefix $uiBuild run build -- --outDir (Join-Path $package 'ui/dist')
if ($LASTEXITCODE -ne 0) { throw "npm build exit $LASTEXITCODE" }
Copy-Tree (Join-Path $root 'workspace/scenarios/pass') (Join-Path $package 'workspace/scenarios/pass') @('runs', 'uploads')
$metaPath = Join-Path $package 'workspace/scenarios/pass/meta.json'
$meta = Get-Content -LiteralPath $metaPath -Raw -Encoding UTF8 | ConvertFrom-Json
$meta.run.state = 'IDLE'
$meta.name = '示例方案（可作模板预填来源）'
[IO.File]::WriteAllText($metaPath, ($meta | ConvertTo-Json -Depth 100) + "`n", $utf8)
New-Item -ItemType Directory -Path (Join-Path $package 'logs') | Out-Null

$helper = @'
import datetime
import io
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import webbrowser
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['APS_SOLVER'] = 'segment'
LOGS = ROOT / 'logs'
LOGS.mkdir(exist_ok=True)


def port_ready():
    try:
        with socket.create_connection(('127.0.0.1', 8765), timeout=0.2):
            return True
    except OSError:
        return False


def start():
    url = 'http://127.0.0.1:8765'
    if port_ready():
        print('程序可能已经在运行', flush=True)
        webbrowser.open(url)
        return 0
    print('关掉本窗口即停止', flush=True)
    logfile = LOGS / ('server-' + datetime.date.today().strftime('%Y%m%d') + '.log')
    with logfile.open('ab') as log:
        process = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'server'], stdout=log, stderr=subprocess.STDOUT)
        try:
            while process.poll() is None and not port_ready():
                time.sleep(0.2)
            if process.poll() is None:
                webbrowser.open(url)
            else:
                print('启动失败，请查看 ' + str(logfile), flush=True)
            return process.wait()
        except KeyboardInterrupt:
            process.terminate()
            return process.wait()


def selfcheck():
    logfile = LOGS / ('selfcheck-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.txt')
    failed = False
    cases = sorted(p.parent for p in (ROOT / 'cases').glob('*/expected.json'))
    total = len(cases) + 1
    print(f'自检共 {total} 项，大约需要 5 分钟，中途不要关闭窗口。', flush=True)
    with logfile.open('w', encoding='utf-8') as log:
        for index, case in enumerate(cases, 1):
            command = [sys.executable, '-X', 'utf8', str(ROOT / 'tools/run_case.py'), str(case)]
            log.write('> ' + subprocess.list2cmdline(command) + '\n')
            log.flush()
            started = time.monotonic()
            code = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT).returncode
            print(f'[第 {index}/共 {total} 项] {case.name} {"通过" if code == 0 else "失败"}（用时 {time.monotonic() - started:.1f} 秒）', flush=True)
            log.write('exit=' + str(code) + '\n')
            failed = failed or code != 0
        command = [sys.executable, '-X', 'utf8', '-m', 'judge.selftest']
        log.write('> ' + subprocess.list2cmdline(command) + '\n')
        log.flush()
        started = time.monotonic()
        code = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT).returncode
        print(f'[第 {total}/共 {total} 项] judge.selftest {"通过" if code == 0 else "失败"}（用时 {time.monotonic() - started:.1f} 秒）', flush=True)
        log.write('exit=' + str(code) + '\n')
        failed = failed or code != 0
        result = '自检有失败' if failed else '自检通过'
        log.write(result + '\n')
    print(str(logfile))
    print(result)
    return int(failed)


def feedback():
    name = '反馈-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip'
    target = ROOT / name
    computer = os.environ['COMPUTERNAME']
    username = os.environ['USERNAME']
    profile = os.environ['USERPROFILE']
    replacements = [(str(ROOT), '<包目录>'), (profile, '<用户目录>'), (computer, '<电脑>'), (username, '<用户>')]
    scan_values = [profile]
    for value in (computer, username):
        if len(value) >= 3:
            scan_values.append(value)
        else:
            # TODO(边界): 用户名或电脑名少于 3 个字符时不按它扫描。
            print('TODO(边界): 用户名或电脑名少于 3 个字符，不按它扫描。')

    def scrub_text(data):
        text = data.decode('utf-8-sig')
        for original, replacement in replacements:
            for variant in (original.replace('\\', '\\\\'), original, original.replace('\\', '/')):
                text = re.sub(re.escape(variant), lambda match: replacement, text, flags=re.IGNORECASE)
        return (b'\xef\xbb\xbf' if data.startswith(b'\xef\xbb\xbf') else b'') + text.encode('utf-8')

    def scrub_xlsx(data):
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as dest:
            for item in source.infolist():
                content = source.read(item)
                fields = {'docProps/core.xml': {'creator', 'lastModifiedBy'}, 'docProps/app.xml': {'Company', 'Manager'}}
                if item.filename in fields:
                    document = ET.fromstring(content)
                    for element in document.iter():
                        if element.tag.rsplit('}', 1)[-1] in fields[item.filename]:
                            element.text = None
                    content = ET.tostring(document, encoding='utf-8', xml_declaration=True)
                dest.writestr(item, content)
        return output.getvalue()

    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        paths = [ROOT / 'VERSION.txt']
        for folder in ('workspace', 'logs'):
            paths.extend([ROOT / folder, *sorted((ROOT / folder).rglob('*'))])
        for path in paths:
            relative = path.relative_to(ROOT).as_posix()
            if path.is_dir():
                archive.writestr(relative + '/', b'')
                continue
            data = path.read_bytes()
            if path.suffix.lower() in ('.txt', '.log', '.json'):
                data = scrub_text(data)
            elif path.suffix.lower() == '.xlsx':
                data = scrub_xlsx(data)
            archive.writestr(relative, data)
    leaked = False
    with zipfile.ZipFile(target) as archive:
        for item in archive.infolist():
            contents = [archive.read(item)]
            if item.filename.lower().endswith('.xlsx'):
                with zipfile.ZipFile(io.BytesIO(contents[0])) as workbook:
                    contents.extend(workbook.read(n) for n in workbook.namelist())
            decoded = [content.decode(encoding, errors='ignore').casefold() for content in contents for encoding in ('utf-8', 'utf-16-le')]
            if any(value.casefold() in item.filename.casefold() for value in scan_values) or any(
                value.casefold() in content for content in decoded for value in scan_values
            ):
                print('反馈包里可能还有设备信息：' + item.filename, flush=True)
                leaked = True
    print(str(target))
    if leaked:
        return 1
    print('反馈包设备信息扫描通过', flush=True)
    os.startfile(str(ROOT))
    return 0


if __name__ == '__main__':
    sys.exit({'start': start, 'selfcheck': selfcheck, 'feedback': feedback}[sys.argv[1]]())
'@
[IO.File]::WriteAllText((Join-Path $package '_release.py'), $helper + "`n", $utf8)
foreach ($entry in @(@('启动', 'start'), @('自检', 'selfcheck'), @('打包反馈', 'feedback'))) {
    $bat = "@echo off`r`nchcp 65001 >nul`r`nsetlocal`r`ncd /d `"%~dp0`"`r`n`"%~dp0python\python.exe`" -X utf8 -u `"%~dp0_release.py`" " + $entry[1] + "`r`nexit /b %errorlevel%`r`n"
    [IO.File]::WriteAllText((Join-Path $package ($entry[0] + '.bat')), $bat, $utf8)
}
$instructions = @'
解压：右键压缩包，选择“全部解压缩”，放到您方便找到的文件夹。请先完成解压，再打开里面的“APS排产”文件夹。文件夹名称可以含中文和空格。

启动：双击“启动.bat”，等待浏览器自动打开排产页面。运行期间请保留启动窗口，关掉本窗口即停止。方案、上传的原始 Excel 和每次运行记录都会保存在本文件夹内的 workspace 中。

填表：填表前请先看“数据填写规则.txt”。交给 Copilot 帮忙填表时，请把这份规则一起交给它。

自检：双击“自检.bat”，等待运行结束。在 logs 文件夹中打开最新的 selfcheck 文本，最后一行显示“自检通过”表示本次自检没有失败；显示“自检有失败”时，请打包反馈。

打包反馈：请先等待排产或自检结束，再双击“打包反馈.bat”。程序会生成“反馈-时间.zip”，扫描设备信息后打开所在文件夹。若提示可能还有设备信息，请把提示的文件名告知维护人员。压缩包里含方案、原始上传文件、运行记录、日志和版本信息。
'@
[IO.File]::WriteAllText((Join-Path $package '使用说明.txt'), $instructions + "`r`n", $utf8)
$template = [IO.File]::ReadAllText((Join-Path $root 'spec/IMPORT_TEMPLATE.md'), $utf8)
$rules = $template.Substring($template.IndexOf('## 3. 填写说明'))
[IO.File]::WriteAllText((Join-Path $package '数据填写规则.txt'), $rules, (New-Object System.Text.UTF8Encoding($true)))
$commit = & git -C $root rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'git rev-parse failed' }
$version = @("Git commit: $commit", ('Build time: ' + (Get-Date -Format 'o')), 'Python: 3.12.10 amd64', 'Dependencies:')
$version += Get-Content -LiteralPath (Join-Path $PSScriptRoot 'release-requirements.txt') -Encoding UTF8
[IO.File]::WriteAllText((Join-Path $package 'VERSION.txt'), ($version -join "`r`n") + "`r`n", $utf8)
@'
from pathlib import Path
import sys
import zipfile
root = Path(sys.argv[1])
with zipfile.ZipFile(sys.argv[2], 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(root.rglob('*')):
        archive.write(path, (Path(root.name) / path.relative_to(root)).as_posix())
print('Package: ' + str(root))
print('Directory bytes: ' + str(sum(p.stat().st_size for p in root.rglob('*') if p.is_file())))
print('Zip: ' + sys.argv[2])
print('Zip bytes: ' + str(Path(sys.argv[2]).stat().st_size))
'@ | & $hostPython - $package $archive
if ($LASTEXITCODE -ne 0) { throw "archive exit $LASTEXITCODE" }
exit 0
