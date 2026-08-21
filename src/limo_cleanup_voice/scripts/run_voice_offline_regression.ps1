# Copyright 2026 DYH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

param(
    [Parameter(Mandatory = $true)]
    [string]$Workspace,
    [Parameter(Mandatory = $true)]
    [string]$Output,
    [Parameter(Mandatory = $true)]
    [string]$FixtureM4a,
    [string]$BundledPython = '',
    [string]$WslDistro = 'Ubuntu-22.04'
)

$ErrorActionPreference = 'Stop'
$workspaceRoot = (Resolve-Path -LiteralPath $Workspace).Path
$outputPath = [System.IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath $outputPath) {
    throw ('Report output already exists; exclusive-create required: {0}' -f `
        $outputPath)
}
if (-not $BundledPython) {
    $BundledPython = Join-Path $env:USERPROFILE `
        '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
}
if (-not (Test-Path -LiteralPath $BundledPython -PathType Leaf)) {
    throw ('Bundled Python is missing: {0}' -f $BundledPython)
}
$packageRoot = Join-Path $workspaceRoot 'src\limo_cleanup_voice'
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $packageRoot
    & $BundledPython -m limo_cleanup_voice.voice_regression_aggregate `
        --workspace $workspaceRoot `
        --output $outputPath `
        --fixture-m4a $FixtureM4a `
        --bundled-python $BundledPython `
        --wsl-distro $WslDistro
    exit $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}
