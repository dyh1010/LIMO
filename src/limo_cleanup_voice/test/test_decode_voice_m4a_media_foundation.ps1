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
    [string]$FixtureM4a,
    [string]$DecoderScript = '',
    [switch]$KeepTemporaryFiles
)

$ErrorActionPreference = 'Stop'

if (-not $DecoderScript) {
    $DecoderScript = Join-Path $PSScriptRoot `
        '..\scripts\decode_voice_m4a_media_foundation.ps1'
}

function Assert-Condition {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

function Invoke-Decoder {
    param(
        [string]$InputDirectory,
        [string]$OutputDirectory
    )
    $windowsPowerShell = Join-Path $env:SystemRoot `
        'System32\WindowsPowerShell\v1.0\powershell.exe'
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $windowsPowerShell `
            -NoProfile `
            -NonInteractive `
            -ExecutionPolicy Bypass `
            -File $scriptPath `
            -InputDirectory $InputDirectory `
            -OutputDirectory $OutputDirectory 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    return [ordered]@{
        exit_code = $exitCode
        output = @($output | ForEach-Object { $_.ToString() })
    }
}

$fixturePath = (Resolve-Path -LiteralPath $FixtureM4a).Path
$scriptPath = (Resolve-Path -LiteralPath $DecoderScript).Path
$temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
    'limo_voice_mf_stale_test_' + [guid]::NewGuid().ToString('N'))
$null = New-Item -ItemType Directory -Path $temporaryRoot

try {
    $inputDirectory = Join-Path $temporaryRoot 'input'
    $null = New-Item -ItemType Directory -Path $inputDirectory
    $fixtureCopy = Join-Path $inputDirectory 'fixture.m4a'
    Copy-Item -LiteralPath $fixturePath -Destination $fixtureCopy
    $sourceHash = (Get-FileHash -LiteralPath $fixtureCopy `
        -Algorithm SHA256).Hash.ToLowerInvariant()
    $expectedName = 'voice_{0}_16k_mono_pcm.wav' -f `
        $sourceHash.Substring(0, 12)

    $staleOutput = Join-Path $inputDirectory 'stale_output'
    $null = New-Item -ItemType Directory -Path $staleOutput
    $staleName = 'voice_000000000000_16k_mono_pcm.wav'
    if ($staleName -eq $expectedName) {
        $staleName = 'voice_111111111111_16k_mono_pcm.wav'
    }
    $stalePath = Join-Path $staleOutput $staleName
    $unrelatedPath = Join-Path $staleOutput 'operator_notes.keep'
    $manifestPath = Join-Path $staleOutput 'decode_manifest.json'
    [System.IO.File]::WriteAllText($stalePath, 'stale sentinel')
    [System.IO.File]::WriteAllText($unrelatedPath, 'unrelated sentinel')
    [System.IO.File]::WriteAllText($manifestPath, 'manifest sentinel')
    $staleHashBefore = (Get-FileHash -LiteralPath $stalePath `
        -Algorithm SHA256).Hash
    $unrelatedHashBefore = (Get-FileHash -LiteralPath $unrelatedPath `
        -Algorithm SHA256).Hash
    $manifestHashBefore = (Get-FileHash -LiteralPath $manifestPath `
        -Algorithm SHA256).Hash

    $staleResult = Invoke-Decoder $inputDirectory $staleOutput
    Assert-Condition ($staleResult.exit_code -ne 0) `
        'A stale generated WAV was not rejected.'
    Assert-Condition (
        ($staleResult.output -join "`n") -match
            [regex]::Escape($staleName)) `
        'The stale-file error did not identify the exact file.'
    Assert-Condition (
        (Get-FileHash -LiteralPath $stalePath -Algorithm SHA256).Hash -eq
            $staleHashBefore) `
        'The stale generated WAV was modified.'
    Assert-Condition (
        (Get-FileHash -LiteralPath $unrelatedPath -Algorithm SHA256).Hash -eq
            $unrelatedHashBefore) `
        'An unrelated output-directory file was modified.'
    Assert-Condition (
        (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash -eq
            $manifestHashBefore) `
        'The existing manifest was modified before stale-file rejection.'
    Assert-Condition (
        -not (Test-Path -LiteralPath (Join-Path $staleOutput $expectedName))) `
        'An expected WAV was written before stale-file rejection.'
    $staleRejectedBeforeWrite = $true

    $rerunOutput = Join-Path $inputDirectory 'rerun_output'
    $null = New-Item -ItemType Directory -Path $rerunOutput
    $rerunUnrelated = Join-Path $rerunOutput 'operator_notes.keep'
    [System.IO.File]::WriteAllText($rerunUnrelated, 'keep across reruns')
    $rerunUnrelatedHash = (Get-FileHash -LiteralPath $rerunUnrelated `
        -Algorithm SHA256).Hash
    $firstRun = Invoke-Decoder $inputDirectory $rerunOutput
    Assert-Condition ($firstRun.exit_code -eq 0) `
        'The first decode run failed.'
    $expectedPath = Join-Path $rerunOutput $expectedName
    Assert-Condition (Test-Path -LiteralPath $expectedPath -PathType Leaf) `
        'The first decode run did not create the expected WAV.'
    $firstManifest = Get-Content -LiteralPath (
        Join-Path $rerunOutput 'decode_manifest.json') -Raw |
        ConvertFrom-Json
    Assert-Condition ($firstManifest.source_root -eq '..') `
        'The manifest source_root is not the direct parent directory.'
    Assert-Condition (
        -not ($firstManifest.cases[0].PSObject.Properties.Name -contains
            'wav_path')) `
        'The manifest contains a non-portable absolute wav_path field.'
    $firstWavHash = (Get-FileHash -LiteralPath $expectedPath `
        -Algorithm SHA256).Hash
    $secondRun = Invoke-Decoder $inputDirectory $rerunOutput
    Assert-Condition ($secondRun.exit_code -eq 0) `
        'The same-input rerun failed.'
    $secondWavHash = (Get-FileHash -LiteralPath $expectedPath `
        -Algorithm SHA256).Hash
    Assert-Condition ($secondWavHash -eq $firstWavHash) `
        'The same-input rerun changed the decoded WAV hash.'
    Assert-Condition (
        (Get-FileHash -LiteralPath $rerunUnrelated -Algorithm SHA256).Hash -eq
            $rerunUnrelatedHash) `
        'The same-input rerun modified an unrelated file.'
    $unrelatedFilesPreserved = $true
    $sameInputRerunPassed = $true

    $emptyInput = Join-Path $temporaryRoot 'empty_input'
    $emptyOutput = Join-Path $emptyInput 'decoded'
    $null = New-Item -ItemType Directory -Path $emptyInput
    $emptyResult = Invoke-Decoder $emptyInput $emptyOutput
    Assert-Condition ($emptyResult.exit_code -ne 0) `
        'An empty input directory was not rejected.'
    Assert-Condition (-not (Test-Path -LiteralPath $emptyOutput)) `
        'The empty-input failure created an output directory.'
    $emptyInputRejected = $true

    $siblingOutput = Join-Path $temporaryRoot 'sibling_output'
    $siblingResult = Invoke-Decoder $inputDirectory $siblingOutput
    Assert-Condition ($siblingResult.exit_code -ne 0) `
        'A sibling output directory was not rejected.'
    Assert-Condition (
        ($siblingResult.output -join "`n") -match
            'direct child of the input directory') `
        'The output-layout error did not explain the trusted layout.'
    Assert-Condition (-not (Test-Path -LiteralPath $siblingOutput)) `
        'The invalid sibling-output failure created a directory.'
    $siblingOutputRejected = $true

    [ordered]@{
        status = 'PASS'
        checks_passed = 5
        stale_generated_file_rejected = $staleRejectedBeforeWrite
        unrelated_files_preserved = $unrelatedFilesPreserved
        same_input_rerun_passed = $sameInputRerunPassed
        empty_input_rejected = $emptyInputRejected
        sibling_output_rejected = $siblingOutputRejected
        fixture_sha256 = $sourceHash
        output_name = $expectedName
        decoded_wav_sha256 = $secondWavHash.ToLowerInvariant()
        temporary_root = $temporaryRoot
    } | ConvertTo-Json
}
finally {
    if (-not $KeepTemporaryFiles -and (Test-Path -LiteralPath $temporaryRoot)) {
        $resolvedTemporaryRoot = (Resolve-Path -LiteralPath $temporaryRoot).Path
        $systemTemporaryRoot = [System.IO.Path]::GetFullPath(
            [System.IO.Path]::GetTempPath()).TrimEnd('\')
        if (-not $resolvedTemporaryRoot.StartsWith(
                $systemTemporaryRoot + '\',
                [System.StringComparison]::OrdinalIgnoreCase)) {
            throw ('Refusing to remove non-temporary path: {0}' -f `
                $resolvedTemporaryRoot)
        }
        Remove-Item -LiteralPath $resolvedTemporaryRoot -Recurse -Force
    }
}
