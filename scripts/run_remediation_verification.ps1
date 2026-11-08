[CmdletBinding()]
param(
    [ValidateSet("Targeted", "Full", "FullPlan", "Verify", "All")]
    [string]$Phase = "Targeted",

    [string]$BaseRef = "main",

    [ValidateRange(2, 32)]
    [int]$FullShardCount = 6,

    [ValidateRange(0, 32)]
    [int]$FullShardIndex = 0,

    [switch]$ResumeFullRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$evidenceDir = Join-Path $repoRoot "evidence\next-step-20260922"
$startedAt = (Get-Date).ToUniversalTime()
$results = [System.Collections.Generic.List[object]]::new()

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtualenv Python not found: $python"
}

New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null
Set-Location -LiteralPath $repoRoot

$previousPythonEncoding = $env:PYTHONIOENCODING
$previousGitNexusBuffer = $env:GITNEXUS_LBUG_BUFFER_POOL_SIZE
$env:PYTHONIOENCODING = "utf-8"

function Invoke-VerificationStep {
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [scriptblock]$Command,

        [System.Collections.IDictionary]$Details
    )

    Write-Host ""
    Write-Host ("=" * 78)
    Write-Host "STEP: $Name"
    Write-Host ("=" * 78)

    $stepStartedAt = (Get-Date).ToUniversalTime()
    $exitCode = 1
    try {
        $global:LASTEXITCODE = 0
        & $Command
        $commandSucceeded = $?
        $nativeExitCode = $LASTEXITCODE
        $exitCode = if ($commandSucceeded -and ($null -eq $nativeExitCode -or $nativeExitCode -eq 0)) { 0 } else { 1 }
    }
    catch {
        Write-Warning ("Step raised an exception: {0}" -f $_.Exception.Message)
        $exitCode = 1
    }

    $stepFinishedAt = (Get-Date).ToUniversalTime()
    $results.Add([ordered]@{
        name = $Name
        exit_code = $exitCode
        started_at = $stepStartedAt.ToString("o")
        finished_at = $stepFinishedAt.ToString("o")
        duration_seconds = [Math]::Round(($stepFinishedAt - $stepStartedAt).TotalSeconds, 3)
        details = $Details
    })

    if ($exitCode -eq 0) {
        Write-Host "[PASS] $Name"
    }
    else {
        Write-Warning "[FAIL] $Name (exit=$exitCode)"
    }

    return $exitCode
}

function Get-PytestInventory {
    $collectionOutput = @(
        & $python -m pytest -o "addopts=" --collect-only -q --disable-warnings 2>&1
    )
    $collectionExitCode = $LASTEXITCODE
    if ($collectionExitCode -ne 0) {
        $collectionOutput | ForEach-Object { Write-Host $_ }
        throw "pytest collection failed with exit code $collectionExitCode"
    }

    $nodeIds = @(
        $collectionOutput |
            ForEach-Object { [string]$_ } |
            Where-Object { $_ -match '^tests[\\/].+\.py::' } |
            Select-Object -Unique
    )
    if ($nodeIds.Count -eq 0) {
        throw "pytest collection returned no test node IDs"
    }

    $fileCounts = [ordered]@{}
    foreach ($nodeId in $nodeIds) {
        $filePath = ($nodeId -split '::', 2)[0].Replace('\\', '/')
        if (-not $fileCounts.Contains($filePath)) {
            $fileCounts[$filePath] = 0
        }
        $fileCounts[$filePath] += 1
    }

    $files = @(
        foreach ($entry in $fileCounts.GetEnumerator()) {
            [pscustomobject]@{
                path = [string]$entry.Key
                test_count = [int]$entry.Value
            }
        }
    )

    return [pscustomobject]@{
        total_tests = $nodeIds.Count
        total_files = $files.Count
        files = $files
    }
}

function New-FullRegressionPlan {
    param(
        [Parameter(Mandatory)]
        [pscustomobject]$Inventory,

        [Parameter(Mandatory)]
        [int]$ShardCount
    )

    $shards = @(
        for ($index = 1; $index -le $ShardCount; $index += 1) {
            [pscustomobject]@{
                index = $index
                expected_tests = 0
                files = [System.Collections.Generic.List[string]]::new()
                junit_path = Join-Path $evidenceDir ("full_regression_shard_{0:D2}_of_{1:D2}.xml" -f $index, $ShardCount)
                log_path = Join-Path $evidenceDir ("full_regression_shard_{0:D2}_of_{1:D2}.log" -f $index, $ShardCount)
            }
        }
    )

    $sortedFiles = @(
        $Inventory.files |
            Sort-Object -Property @{ Expression = "test_count"; Descending = $true }, @{ Expression = "path"; Descending = $false }
    )
    foreach ($file in $sortedFiles) {
        $target = $shards |
            Sort-Object -Property @{ Expression = "expected_tests"; Descending = $false }, @{ Expression = "index"; Descending = $false } |
            Select-Object -First 1
        [void]$target.files.Add($file.path)
        $target.expected_tests += $file.test_count
    }

    foreach ($shard in $shards) {
        $shard.files = @($shard.files | Sort-Object)
    }

    return [pscustomobject]@{
        schema_version = 1
        generated_at = (Get-Date).ToUniversalTime().ToString("o")
        total_collected_tests = $Inventory.total_tests
        total_collected_files = $Inventory.total_files
        shard_count = $ShardCount
        shards = $shards
    }
}

function Get-FullRegressionPlanIdentity {
    param(
        [Parameter(Mandatory)]
        [pscustomobject]$Plan
    )

    $identity = [ordered]@{
        total_collected_tests = [int]$Plan.total_collected_tests
        total_collected_files = [int]$Plan.total_collected_files
        shard_count = [int]$Plan.shard_count
        shards = @(
            foreach ($shard in $Plan.shards) {
                [ordered]@{
                    index = [int]$shard.index
                    expected_tests = [int]$shard.expected_tests
                    files = @($shard.files | ForEach-Object { [string]$_ })
                }
            }
        )
    }
    return ($identity | ConvertTo-Json -Depth 8 -Compress)
}

function Test-ReusableShardJunit {
    param(
        [Parameter(Mandatory)]
        [pscustomobject]$Shard,

        [Parameter(Mandatory)]
        [datetime]$PlanGeneratedAt
    )

    if (-not (Test-Path -LiteralPath $Shard.junit_path)) {
        return $false
    }
    if ((Get-Item -LiteralPath $Shard.junit_path).LastWriteTimeUtc -lt $PlanGeneratedAt.ToUniversalTime()) {
        return $false
    }

    try {
        [xml]$source = Get-Content -Raw -LiteralPath $Shard.junit_path
        $sourceSuites = @($source.SelectNodes("/testsuites/testsuite | /testsuite"))
        if ($sourceSuites.Count -eq 0) {
            return $false
        }

        $tests = 0
        $failures = 0
        $errors = 0
        $testCases = 0
        foreach ($sourceSuite in $sourceSuites) {
            $tests += [int]$sourceSuite.GetAttribute("tests")
            $failures += [int]$sourceSuite.GetAttribute("failures")
            $errors += [int]$sourceSuite.GetAttribute("errors")
            $testCases += @($sourceSuite.SelectNodes("./testcase")).Count
        }

        return (
            $tests -ge $testCases -and
            $testCases -eq [int]$Shard.expected_tests -and
            $failures -eq 0 -and
            $errors -eq 0
        )
    }
    catch {
        return $false
    }
}

function Merge-PytestJunit {
    param(
        [Parameter(Mandatory)]
        [pscustomobject]$Plan,

        [Parameter(Mandatory)]
        [string]$OutputPath
    )

    $combined = [System.Xml.XmlDocument]::new()
    [void]$combined.AppendChild($combined.CreateXmlDeclaration("1.0", "utf-8", $null))
    $root = $combined.CreateElement("testsuites")
    [void]$combined.AppendChild($root)
    $suite = $combined.CreateElement("testsuite")
    $suite.SetAttribute("name", "pytest full regression shards")
    [void]$root.AppendChild($suite)

    $totals = [ordered]@{
        tests = 0
        pytest_reported_tests = 0
        failures = 0
        errors = 0
        skipped = 0
        time = 0.0
    }
    foreach ($shard in $Plan.shards) {
        if (-not (Test-Path -LiteralPath $shard.junit_path)) {
            throw "Missing shard JUnit: $($shard.junit_path)"
        }

        [xml]$source = Get-Content -Raw -LiteralPath $shard.junit_path
        $sourceSuites = @($source.SelectNodes("/testsuites/testsuite | /testsuite"))
        if ($sourceSuites.Count -eq 0) {
            throw "Shard JUnit has no testsuite: $($shard.junit_path)"
        }

        $shardTests = 0
        foreach ($sourceSuite in $sourceSuites) {
            $sourceTestCases = @($sourceSuite.SelectNodes("./testcase"))
            $sourceReportedTests = [int]$sourceSuite.GetAttribute("tests")
            if ($sourceReportedTests -lt $sourceTestCases.Count) {
                throw "Shard JUnit reports fewer tests than testcase elements: $($shard.junit_path)"
            }
            $shardTests += $sourceTestCases.Count
            $totals.tests += $sourceTestCases.Count
            $totals.pytest_reported_tests += $sourceReportedTests
            $totals.failures += [int]$sourceSuite.GetAttribute("failures")
            $totals.errors += [int]$sourceSuite.GetAttribute("errors")
            $totals.skipped += [int]$sourceSuite.GetAttribute("skipped")
            $totals.time += [double]$sourceSuite.GetAttribute("time")
            foreach ($testCase in $sourceTestCases) {
                [void]$suite.AppendChild($combined.ImportNode($testCase, $true))
            }
        }

        if ($shardTests -ne $shard.expected_tests) {
            throw "Shard $($shard.index) recorded $shardTests tests; expected $($shard.expected_tests)"
        }
    }

    if ($totals.tests -ne $Plan.total_collected_tests) {
        throw "Merged JUnit recorded $($totals.tests) tests; collection inventory expected $($Plan.total_collected_tests)"
    }

    $root.SetAttribute("name", "pytest tests")
    $suite.SetAttribute("tests", [string]$totals.tests)
    $suite.SetAttribute("failures", [string]$totals.failures)
    $suite.SetAttribute("errors", [string]$totals.errors)
    $suite.SetAttribute("skipped", [string]$totals.skipped)
    $suite.SetAttribute("time", [string]([Math]::Round($totals.time, 3)))
    $suite.SetAttribute("timestamp", $startedAt.ToString("o"))
    $suite.SetAttribute("hostname", $env:COMPUTERNAME)
    $properties = $combined.CreateElement("properties")
    $reportedTestsProperty = $combined.CreateElement("property")
    $reportedTestsProperty.SetAttribute("name", "pytest_reported_tests_including_subtests")
    $reportedTestsProperty.SetAttribute("value", [string]$totals.pytest_reported_tests)
    [void]$properties.AppendChild($reportedTestsProperty)
    [void]$suite.InsertBefore($properties, $suite.FirstChild)
    $combined.Save($OutputPath)

    return [pscustomobject]$totals
}

$targetedTests = @(
    "tests/ml/test_h14_integrity.py",
    "tests/ml/test_model_coverage_mc8_manifest_worktree.py",
    "tests/ml/test_model_coverage_mc9_authorization.py",
    "tests/ml/test_model_coverage_mc9_release_identity.py",
    "tests/ml/test_model_coverage_mc9_seal.py",
    "tests/ml/test_p7_a4_resume_contract.py",
    "tests/ml/test_p8_economic_evaluation.py",
    "tests/test_stage1_pipeline.py",
    "tests/test_validate_alternative_history.py",
    "tests/test_runtime_migration_preflight.py"
)

try {
    if ($Phase -in @("Targeted", "All")) {
        $targetedJunit = Join-Path $evidenceDir "targeted_remediation_junit.xml"
        [void](Invoke-VerificationStep -Name "Targeted remediation tests" -Command {
            & $python -m pytest -s --tb=short "--junitxml=$targetedJunit" @targetedTests
        })
    }

    if ($Phase -in @("Full", "FullPlan", "All")) {
        $script:fullInventory = $null
        $script:fullPlan = $null
        $script:previousFullPlan = $null
        $script:resumePlanCompatible = $false
        $planPath = Join-Path $evidenceDir "full_regression_plan.json"
        $planExitCode = Invoke-VerificationStep -Name "Full regression collection plan" -Details ([ordered]@{
            shard_count = $FullShardCount
            plan_path = $planPath
            resume_requested = [bool]$ResumeFullRun
        }) -Command {
            if ($ResumeFullRun -and (Test-Path -LiteralPath $planPath)) {
                try {
                    $script:previousFullPlan = Get-Content -Raw -LiteralPath $planPath | ConvertFrom-Json
                }
                catch {
                    Write-Warning "Existing full regression plan is unreadable; all shards will run again."
                }
            }
            $script:fullInventory = Get-PytestInventory
            $script:fullPlan = New-FullRegressionPlan -Inventory $script:fullInventory -ShardCount $FullShardCount
            if ($null -ne $script:previousFullPlan) {
                $script:resumePlanCompatible = (
                    (Get-FullRegressionPlanIdentity -Plan $script:previousFullPlan) -ceq
                    (Get-FullRegressionPlanIdentity -Plan $script:fullPlan)
                )
                if (-not $script:resumePlanCompatible) {
                    Write-Warning "Existing full regression plan does not match the current collection; all shards will run again."
                }
            }
            $script:fullPlan | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $planPath -Encoding utf8
            Write-Host (
                "Collected {0} tests from {1} files into {2} shards." -f
                    $script:fullPlan.total_collected_tests,
                    $script:fullPlan.total_collected_files,
                    $script:fullPlan.shard_count
            )
            foreach ($shard in $script:fullPlan.shards) {
                Write-Host (
                    "  shard {0}/{1}: {2} tests across {3} files" -f
                        $shard.index,
                        $script:fullPlan.shard_count,
                        $shard.expected_tests,
                        $shard.files.Count
                )
            }
        }

        if ($Phase -ne "FullPlan" -and $planExitCode -eq 0) {
            if ($FullShardIndex -gt $script:fullPlan.shard_count) {
                throw "FullShardIndex $FullShardIndex exceeds shard count $($script:fullPlan.shard_count)"
            }
            $shardsToRun = if ($FullShardIndex -eq 0) {
                @($script:fullPlan.shards)
            }
            else {
                @($script:fullPlan.shards | Where-Object { $_.index -eq $FullShardIndex })
            }

            foreach ($shard in $shardsToRun) {
                $reuseShard = $false
                if ($ResumeFullRun -and $script:resumePlanCompatible) {
                    $previousPlanGeneratedAt = [datetime]::Parse(
                        [string]$script:previousFullPlan.generated_at,
                        [System.Globalization.CultureInfo]::InvariantCulture,
                        [System.Globalization.DateTimeStyles]::RoundtripKind
                    )
                    $reuseShard = Test-ReusableShardJunit `
                        -Shard $shard `
                        -PlanGeneratedAt $previousPlanGeneratedAt
                }

                if ($reuseShard) {
                    $stepName = "Full regression shard {0}/{1} (reused)" -f $shard.index, $script:fullPlan.shard_count
                    [void](Invoke-VerificationStep -Name $stepName -Details ([ordered]@{
                        shard_index = $shard.index
                        shard_count = $script:fullPlan.shard_count
                        expected_tests = $shard.expected_tests
                        file_count = $shard.files.Count
                        junit_path = $shard.junit_path
                        log_path = $shard.log_path
                        reused = $true
                    }) -Command {
                        Write-Host "Reusing validated shard JUnit: $($shard.junit_path)"
                    })
                    continue
                }

                if (Test-Path -LiteralPath $shard.junit_path) {
                    Remove-Item -LiteralPath $shard.junit_path -Force
                }
                if (Test-Path -LiteralPath $shard.log_path) {
                    Remove-Item -LiteralPath $shard.log_path -Force
                }

                $stepName = "Full regression shard {0}/{1}" -f $shard.index, $script:fullPlan.shard_count
                [void](Invoke-VerificationStep -Name $stepName -Details ([ordered]@{
                    shard_index = $shard.index
                    shard_count = $script:fullPlan.shard_count
                    expected_tests = $shard.expected_tests
                    file_count = $shard.files.Count
                    junit_path = $shard.junit_path
                    log_path = $shard.log_path
                    reused = $false
                }) -Command {
                    $previousPythonUnbuffered = $env:PYTHONUNBUFFERED
                    $previousErrorActionPreference = $ErrorActionPreference
                    $env:PYTHONUNBUFFERED = "1"
                    $ErrorActionPreference = "Continue"
                    $pytestExitCode = 1
                    try {
                        & $python -m pytest -o "addopts=" -vv -s --tb=short "--junitxml=$($shard.junit_path)" @($shard.files) 2>&1 |
                            Tee-Object -FilePath $shard.log_path
                        $pytestExitCode = $LASTEXITCODE
                    }
                    finally {
                        $env:PYTHONUNBUFFERED = $previousPythonUnbuffered
                        $ErrorActionPreference = $previousErrorActionPreference
                    }
                    $global:LASTEXITCODE = $pytestExitCode
                })
            }

            if ($FullShardIndex -eq 0) {
                $fullJunit = Join-Path $evidenceDir "full_regression_junit.xml"
                [void](Invoke-VerificationStep -Name "Full regression evidence aggregation" -Details ([ordered]@{
                    expected_tests = $script:fullPlan.total_collected_tests
                    shard_count = $script:fullPlan.shard_count
                    junit_path = $fullJunit
                }) -Command {
                    $merged = Merge-PytestJunit -Plan $script:fullPlan -OutputPath $fullJunit
                    if ($merged.failures -ne 0 -or $merged.errors -ne 0) {
                        throw "Merged JUnit contains failures=$($merged.failures), errors=$($merged.errors)"
                    }
                    Write-Host (
                        "Merged {0} tests: failures={1}, errors={2}, skipped={3}." -f
                            $merged.tests,
                            $merged.failures,
                            $merged.errors,
                            $merged.skipped
                    )
                })
            }
        }
    }

    if ($Phase -in @("Verify", "All")) {
        [void](Invoke-VerificationStep -Name "Git whitespace check" -Command {
            & git -c "core.whitespace=trailing-space,space-before-tab,cr-at-eol" diff --cached --check
        })

        $env:GITNEXUS_LBUG_BUFFER_POOL_SIZE = "0"
        [void](Invoke-VerificationStep -Name "GitNexus refresh" -Command {
            & node .gitnexus/run.cjs analyze --index-only
        })
        [void](Invoke-VerificationStep -Name "GitNexus change detection" -Command {
            & node .gitnexus/run.cjs detect-changes --repo besttime-crypto --scope compare --base-ref $BaseRef
        })
    }
}
finally {
    $env:PYTHONIOENCODING = $previousPythonEncoding
    $env:GITNEXUS_LBUG_BUFFER_POOL_SIZE = $previousGitNexusBuffer
}

$finishedAt = (Get-Date).ToUniversalTime()
$failedSteps = @($results | Where-Object { $_.exit_code -ne 0 })
$summary = [ordered]@{
    schema_version = 1
    phase = $Phase
    base_ref = $BaseRef
    repo_root = $repoRoot
    started_at = $startedAt.ToString("o")
    finished_at = $finishedAt.ToString("o")
    duration_seconds = [Math]::Round(($finishedAt - $startedAt).TotalSeconds, 3)
    overall_status = if ($failedSteps.Count -eq 0) { "PASS" } else { "FAIL" }
    steps = $results
}

$summaryFileName = if ($Phase -eq "FullPlan") {
    "manual_verification_full_plan_summary.json"
}
elseif ($Phase -eq "Full" -and $FullShardIndex -gt 0) {
    "manual_verification_full_shard_{0:D2}_of_{1:D2}_summary.json" -f $FullShardIndex, $FullShardCount
}
else {
    "manual_verification_summary.json"
}
$summaryPath = Join-Path $evidenceDir $summaryFileName
$summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $summaryPath -Encoding utf8

Write-Host ""
Write-Host "Verification summary: $summaryPath"
Write-Host "Overall status: $($summary.overall_status)"

if ($failedSteps.Count -ne 0) {
    exit 1
}

exit 0
