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
    [string]$InputDirectory,
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime

function Await-Operation {
    param($Operation, [Type]$ResultType)
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and
            $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        } | Select-Object -First 1
    $task = $method.MakeGenericMethod($ResultType).Invoke(
        $null, @($Operation))
    return $task.GetAwaiter().GetResult()
}

function Await-ActionWithProgress {
    param($Operation, [Type]$ProgressType)
    $method = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and
            $_.GetGenericArguments().Count -eq 1 -and
            $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq
                'IAsyncActionWithProgress`1'
        } | Select-Object -First 1
    $task = $method.MakeGenericMethod($ProgressType).Invoke(
        $null, @($Operation))
    $null = $task.GetAwaiter().GetResult()
}

function Get-RelativePathCompat {
    param([string]$BaseDirectory, [string]$TargetPath)
    $basePath = $BaseDirectory.TrimEnd('\', '/') + '\'
    $targetDirectoryPath = $TargetPath.TrimEnd('\', '/') + '\'
    $baseUri = [System.Uri]::new($basePath)
    $targetUri = [System.Uri]::new($targetDirectoryPath)
    if ($baseUri.Scheme -ne $targetUri.Scheme) {
        throw 'Cannot make a relative path across URI schemes.'
    }
    return [System.Uri]::UnescapeDataString(
        $baseUri.MakeRelativeUri($targetUri).ToString())
}

function Get-Pcm16WavStatistics {
    param([string]$Path)
    $stream = [System.IO.File]::OpenRead($Path)
    $reader = [System.IO.BinaryReader]::new($stream)
    try {
        if ((-join $reader.ReadChars(4)) -ne 'RIFF') {
            throw 'WAV file does not start with RIFF.'
        }
        $null = $reader.ReadUInt32()
        if ((-join $reader.ReadChars(4)) -ne 'WAVE') {
            throw 'RIFF file is not WAVE.'
        }
        $formatTag = 0
        $channels = 0
        $sampleRate = 0
        $bitsPerSample = 0
        $dataOffset = 0L
        $dataLength = 0L
        while ($stream.Position + 8 -le $stream.Length) {
            $chunkId = -join $reader.ReadChars(4)
            $chunkLength = [int64]$reader.ReadUInt32()
            $chunkStart = $stream.Position
            if ($chunkId -eq 'fmt ') {
                $formatTag = $reader.ReadUInt16()
                $channels = $reader.ReadUInt16()
                $sampleRate = $reader.ReadUInt32()
                $null = $reader.ReadUInt32()
                $null = $reader.ReadUInt16()
                $bitsPerSample = $reader.ReadUInt16()
            }
            elseif ($chunkId -eq 'data') {
                $dataOffset = $chunkStart
                $dataLength = $chunkLength
            }
            $next = $chunkStart + $chunkLength + ($chunkLength % 2)
            $null = $stream.Seek($next, [System.IO.SeekOrigin]::Begin)
        }
        if (
            $formatTag -ne 1 -or $channels -ne 1 -or
            $sampleRate -ne 16000 -or $bitsPerSample -ne 16 -or
            $dataLength -le 0
        ) {
            throw 'Decoded WAV is not 16 kHz mono PCM16.'
        }

        $null = $stream.Seek($dataOffset, [System.IO.SeekOrigin]::Begin)
        $sampleCount = [int64]($dataLength / 2)
        $sumSquares = [double]0
        $peak = 0
        $clipped = [int64]0
        $frameSamples = 320
        $frameSumSquares = [double]0
        $frameSampleCount = 0
        $frameRms = [System.Collections.Generic.List[double]]::new()
        for ($index = 0L; $index -lt $sampleCount; $index++) {
            $sample = [int]$reader.ReadInt16()
            $absolute = [Math]::Abs($sample)
            $square = [double]$sample * [double]$sample
            $sumSquares += $square
            $frameSumSquares += $square
            $frameSampleCount++
            if ($absolute -gt $peak) {
                $peak = $absolute
            }
            if ($absolute -ge 32760) {
                $clipped++
            }
            if ($frameSampleCount -eq $frameSamples) {
                $frameRms.Add([Math]::Sqrt(
                    $frameSumSquares / $frameSampleCount))
                $frameSumSquares = [double]0
                $frameSampleCount = 0
            }
        }
        if ($frameSampleCount -gt 0) {
            $frameRms.Add([Math]::Sqrt(
                $frameSumSquares / $frameSampleCount))
        }
        $rms = [Math]::Sqrt($sumSquares / $sampleCount)
        $sorted = $frameRms.ToArray()
        [Array]::Sort($sorted)
        $floorIndex = [Math]::Floor(($sorted.Length - 1) * 0.2)
        $speechGate = [Math]::Max(300.0, $sorted[$floorIndex] * 3.0)
        $firstVoiced = -1
        $lastVoiced = -1
        $voiced = 0
        for ($index = 0; $index -lt $frameRms.Count; $index++) {
            if ($frameRms[$index] -ge $speechGate) {
                if ($firstVoiced -lt 0) {
                    $firstVoiced = $index
                }
                $lastVoiced = $index
                $voiced++
            }
        }
        $duration = [double]$sampleCount / $sampleRate
        $frameDuration = [double]$frameSamples / $sampleRate
        $leading = if ($firstVoiced -ge 0) {
            $firstVoiced * $frameDuration
        } else {
            $duration
        }
        $trailing = if ($lastVoiced -ge 0) {
            [Math]::Max(
                0.0, $duration - (($lastVoiced + 1) * $frameDuration))
        } else {
            $duration
        }
        $rmsDbfs = if ($rms -gt 0) {
            20.0 * [Math]::Log10($rms / 32768.0)
        } else {
            $null
        }
        $peakDbfs = if ($peak -gt 0) {
            20.0 * [Math]::Log10($peak / 32768.0)
        } else {
            $null
        }
        return [ordered]@{
            sample_rate = [int]$sampleRate
            channels = [int]$channels
            sample_width_bytes = 2
            frame_count = $sampleCount
            duration_sec = [Math]::Round($duration, 6)
            rms = [Math]::Round($rms, 2)
            rms_dbfs = if ($null -eq $rmsDbfs) {
                $null
            } else {
                [Math]::Round($rmsDbfs, 2)
            }
            peak = $peak
            peak_dbfs = if ($null -eq $peakDbfs) {
                $null
            } else {
                [Math]::Round($peakDbfs, 2)
            }
            clipped_fraction = [Math]::Round(
                [double]$clipped / $sampleCount, 8)
            voiced_frame_fraction = [Math]::Round(
                [double]$voiced / $frameRms.Count, 4)
            leading_silence_sec_est = [Math]::Round($leading, 3)
            trailing_silence_sec_est = [Math]::Round($trailing, 3)
        }
    }
    finally {
        $reader.Dispose()
        $stream.Dispose()
    }
}

$storageFileType = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$storageFolderType = [Windows.Storage.StorageFolder,Windows.Storage,ContentType=WindowsRuntime]
$collisionType = [Windows.Storage.CreationCollisionOption,Windows.Storage,ContentType=WindowsRuntime]
$profileType = [Windows.Media.MediaProperties.MediaEncodingProfile,Windows.Media.MediaProperties,ContentType=WindowsRuntime]
$qualityType = [Windows.Media.MediaProperties.AudioEncodingQuality,Windows.Media.MediaProperties,ContentType=WindowsRuntime]
$transcoderType = [Windows.Media.Transcoding.MediaTranscoder,Windows.Media.Transcoding,ContentType=WindowsRuntime]
$prepareType = [Windows.Media.Transcoding.PrepareTranscodeResult,Windows.Media.Transcoding,ContentType=WindowsRuntime]

$inputRoot = (Resolve-Path -LiteralPath $InputDirectory).Path
$sourceItems = @(
    Get-ChildItem -LiteralPath $inputRoot -File -Filter '*.m4a' |
        Sort-Object Name
)
if ($sourceItems.Count -eq 0) {
    throw ('No .m4a files found directly under {0}.' -f $inputRoot)
}
$sourceRecords = @()
$expectedOutputNames = @{}
foreach ($sourceItem in $sourceItems) {
    $sourceHash = (Get-FileHash -Algorithm SHA256 `
        -LiteralPath $sourceItem.FullName).Hash.ToLowerInvariant()
    $outputName = 'voice_{0}_16k_mono_pcm.wav' -f `
        $sourceHash.Substring(0, 12)
    if ($expectedOutputNames.ContainsKey($outputName)) {
        throw ('Multiple inputs map to the same output name: {0}.' -f `
            $outputName)
    }
    $expectedOutputNames[$outputName] = $true
    $sourceRecords += [ordered]@{
        item = $sourceItem
        sha256 = $sourceHash
        output_name = $outputName
    }
}

$outputCandidate = [System.IO.Path]::GetFullPath($OutputDirectory)
$candidateParent = [System.IO.Directory]::GetParent($outputCandidate)
if (
    $null -eq $candidateParent -or
    -not $inputRoot.Equals(
        $candidateParent.FullName,
        [System.StringComparison]::OrdinalIgnoreCase)
) {
    $layoutMessage = (
        'Output directory must be a direct child of the input directory ' +
        'so source_root remains exactly "..".')
    throw $layoutMessage
}

if (Test-Path -LiteralPath $OutputDirectory) {
    if (-not (Test-Path -LiteralPath $OutputDirectory -PathType Container)) {
        throw ('Output path is not a directory: {0}.' -f $OutputDirectory)
    }
    $outputRoot = (Resolve-Path -LiteralPath $OutputDirectory).Path
    $generatedNamePattern =
        '^voice_[0-9a-f]{12}_16k_mono_pcm[.]wav$'
    $staleGeneratedFiles = @(
        Get-ChildItem -LiteralPath $outputRoot -File |
            Where-Object {
                $_.Name -match $generatedNamePattern -and
                -not $expectedOutputNames.ContainsKey($_.Name)
            } |
            Sort-Object Name
    )
    if ($staleGeneratedFiles.Count -gt 0) {
        $staleNames = $staleGeneratedFiles.Name -join ', '
        $staleMessage = (
            'Output directory contains stale generated WAV file(s): {0}. ' +
            'Move them aside or use an empty output directory.')
        throw ($staleMessage -f $staleNames)
    }
}
else {
    $null = New-Item -ItemType Directory -Path $OutputDirectory
    $outputRoot = (Resolve-Path -LiteralPath $OutputDirectory).Path
}
$outputFolder = Await-Operation (
    $storageFolderType::GetFolderFromPathAsync($outputRoot)) $storageFolderType

$records = @()
$wakeOnlyLabel = -join ([char[]](0x5c0f, 0x83ab, 0x5c0f, 0x83ab))
$priorityStopLabel = -join ([char[]](0x505c, 0x4e0b))
$relativeSourceRoot = '..'
foreach ($sourceRecord in $sourceRecords) {
    $sourceItem = $sourceRecord.item
    $sourceHash = $sourceRecord.sha256
    $outputName = $sourceRecord.output_name
    $sourceLabel = [regex]::Replace(
        $sourceItem.BaseName, '[0-9]+$', '')
    $source = Await-Operation (
        $storageFileType::GetFileFromPathAsync($sourceItem.FullName)) `
        $storageFileType
    $sourceProfile = Await-Operation (
        $profileType::CreateFromFileAsync($source)) $profileType
    $destination = Await-Operation (
        $outputFolder.CreateFileAsync(
            $outputName, $collisionType::ReplaceExisting)) $storageFileType
    $profile = $profileType::CreateWav($qualityType::Low)
    if (
        $profile.Audio.SampleRate -ne 16000 -or
        $profile.Audio.ChannelCount -ne 1 -or
        $profile.Audio.BitsPerSample -ne 16
    ) {
        throw 'Media Foundation Low WAV profile is not 16 kHz mono PCM16.'
    }
    $transcoder = $transcoderType::new()
    $transcoder.AlwaysReencode = $true
    $prepared = Await-Operation (
        $transcoder.PrepareFileTranscodeAsync(
            $source, $destination, $profile)) $prepareType
    if (-not $prepared.CanTranscode) {
        throw ('Cannot transcode {0}: {1}' -f `
            $sourceItem.Name, $prepared.FailureReason)
    }
    Await-ActionWithProgress ($prepared.TranscodeAsync()) ([double])
    $outputPath = Join-Path $outputRoot $outputName
    $wavStatistics = Get-Pcm16WavStatistics $outputPath
    $records += [ordered]@{
        source_name = $sourceItem.Name
        id = 'voice-{0}' -f $sourceHash.Substring(0, 12)
        label = $sourceLabel
        coverage_class = if (
            $sourceLabel -eq $wakeOnlyLabel
        ) {
            'wake_only'
        } elseif (
            $sourceLabel -eq $priorityStopLabel
        ) {
            'priority_stop'
        } else {
            'ordinary_intent'
        }
        source_path = $sourceItem.Name
        source_sha256 = $sourceHash
        source_bytes = $sourceItem.Length
        source_format = [ordered]@{
            subtype = $sourceProfile.Audio.Subtype
            sample_rate = $sourceProfile.Audio.SampleRate
            channels = $sourceProfile.Audio.ChannelCount
            bits_per_sample = $sourceProfile.Audio.BitsPerSample
            bitrate = $sourceProfile.Audio.Bitrate
        }
        audio_path = $outputName
        wav_sha256 = (Get-FileHash -Algorithm SHA256 `
            -LiteralPath $outputPath).Hash.ToLowerInvariant()
        wav_bytes = (Get-Item -LiteralPath $outputPath).Length
        wav = $wavStatistics
        transcription_status = 'decoded_not_transcribed'
        transcript = $null
        intent_status = 'not_evaluated_without_asr'
        label_is_transcript = $false
    }
}

$manifest = [ordered]@{
    schema_version = 2
    mode = 'windows_media_foundation_offline_no_ros'
    label_policy = 'filename_labels_are_prompts_not_transcripts'
    source_root = $relativeSourceRoot
    required_coverage_classes = @(
        'wake_only',
        'priority_stop',
        'ordinary_intent'
    )
    cases = $records
}
$manifestPath = Join-Path $outputRoot 'decode_manifest.json'
$manifestJson = $manifest | ConvertTo-Json -Depth 6
$utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText(
    $manifestPath,
    $manifestJson + [System.Environment]::NewLine,
    $utf8WithoutBom)
Write-Output $manifestJson
Write-Output ('Manifest: {0}' -f $manifestPath)
