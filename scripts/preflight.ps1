# Verifies the toolchain and AWS access before you start building.
#   powershell -ExecutionPolicy Bypass -File scripts\preflight.ps1

$ErrorActionPreference = "Continue"
$script:fail = 0

function Check($name, $ok, $detail) {
    if ($ok) { Write-Host "  [ok]   $name" -ForegroundColor Green }
    else     { Write-Host "  [FAIL] $name" -ForegroundColor Red; $script:fail++ }
    if ($detail) { Write-Host "         $detail" -ForegroundColor DarkGray }
}

# Resolve aws.exe explicitly. A freshly-installed CLI is not on PATH in shells
# that were already open, so fall back to the default install location.
function Resolve-Aws {
    $cmd = Get-Command aws -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $fallback = "C:\Program Files\Amazon\AWSCLIV2\aws.exe"
    if (Test-Path $fallback) { return $fallback }
    return $null
}

# Run a command and return @{ Ok; Output }. Guards against the
# CommandNotFoundException case, where $LASTEXITCODE keeps its previous value.
function Invoke-Checked($exe, $argList) {
    if (-not $exe) { return @{ Ok = $false; Output = "executable not found" } }
    $global:LASTEXITCODE = 0
    $out = & $exe @argList 2>&1 | Out-String
    return @{ Ok = ($LASTEXITCODE -eq 0); Output = $out.Trim() }
}

Write-Host "`n== Toolchain ==" -ForegroundColor Cyan
$awsExe = Resolve-Aws
Check "aws" ($null -ne $awsExe) $(if ($awsExe) { $awsExe } else { "install: winget install --id Amazon.AWSCLI -e" })
if ($awsExe -and -not (Get-Command aws -ErrorAction SilentlyContinue)) {
    Write-Host "         NOTE: found on disk but not on this shell's PATH." -ForegroundColor Yellow
    Write-Host "         Open a NEW terminal to pick it up." -ForegroundColor Yellow
}
foreach ($t in @("uv", "git", "python")) {
    $cmd = Get-Command $t -ErrorAction SilentlyContinue
    Check $t ($null -ne $cmd) $(if ($cmd) { $cmd.Source })
}

Write-Host "`n== Python deps ==" -ForegroundColor Cyan
$global:LASTEXITCODE = 0
$v = (uv run python -c "from importlib.metadata import version; print(version('strands-agents'))" 2>&1 | Out-String).Trim()
Check "strands-agents importable" ($LASTEXITCODE -eq 0) "version $v"

Write-Host "`n== AWS credentials ==" -ForegroundColor Cyan
$r = Invoke-Checked $awsExe @("sts", "get-caller-identity", "--output", "json")
if ($r.Ok) {
    $acct = ($r.Output | ConvertFrom-Json).Account
    Check "sts:GetCallerIdentity" $true "account $acct"
} else {
    Check "sts:GetCallerIdentity" $false "run: aws configure --profile agents-for-humans"
}

Write-Host "`n== Bedrock model access ==" -ForegroundColor Cyan
$region = if ($env:AWS_REGION) { $env:AWS_REGION } else { "us-west-2" }
if (-not $r.Ok) {
    Check "bedrock ($region)" $false "skipped - no valid AWS credentials"
} else {
    $m = Invoke-Checked $awsExe @("bedrock", "list-foundation-models", "--region", $region, "--output", "json")
    if ($m.Ok) {
        $n = ($m.Output | ConvertFrom-Json).modelSummaries.Count
        Check "bedrock:ListFoundationModels ($region)" ($n -gt 0) "$n models visible"
        Write-Host "         NOTE: visibility != access. Enable model access here:" -ForegroundColor DarkGray
        Write-Host "         https://console.aws.amazon.com/bedrock/home#/modelaccess" -ForegroundColor DarkGray
    } else {
        Check "bedrock:ListFoundationModels ($region)" $false "check IAM permissions and region"
    }
}

Write-Host ""
if ($script:fail -eq 0) { Write-Host "All checks passed.`n" -ForegroundColor Green }
else { Write-Host "$script:fail check(s) failed - see above.`n" -ForegroundColor Red }
exit $script:fail
