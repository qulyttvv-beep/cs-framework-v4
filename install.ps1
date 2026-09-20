# install.ps1 - installs everything CS Framework needs on Windows
$ErrorActionPreference = "Continue"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CsPy       = Join-Path $ProjectDir "cs.py"
if (-not (Test-Path $CsPy)) { throw "cs.py not found next to this script" }

function Head($t)  { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Ok($t)    { Write-Host "  [+] $t" -ForegroundColor Green }
function Warn($t)  { Write-Host "  [!] $t" -ForegroundColor Yellow }
function Err($t)   { Write-Host "  [X] $t" -ForegroundColor Red }

function Refresh-Path {
    $m = [Environment]::GetEnvironmentVariable("Path","Machine")
    $u = [Environment]::GetEnvironmentVariable("Path","User")
    $env:Path = "$m;$u"
}

function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Wg($id, $label) {
    Write-Host "  [*] winget install $label" -ForegroundColor Cyan
    winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
    Refresh-Path
    if (Have ($label -replace ' .*','')) { Ok "$label ready" } else { Warn "$label not verified" }
}

Head "1. prerequisites"
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Err "winget not available. install 'App Installer' from the Microsoft Store."
    exit 1
}
Ok "winget found"

if (-not (Have python)) { Wg "Python.Python.3.12" "Python 3.12" } else { Ok "python present" }
if (-not (Have git))    { Wg "Git.Git"           "Git" }          else { Ok "git present" }
if (-not (Have cmake))  { Wg "Kitware.CMake"     "CMake" }        else { Ok "cmake present" }
if (-not (Have ninja))  { Wg "Ninja-build.Ninja" "Ninja" }        else { Ok "ninja present" }

Head "2. Visual Studio Build Tools + C++ workload"
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$hasVC = $false
if (Test-Path $vswhere) {
    $vc = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath -nologo 2>$null
    if ($vc) { Ok "MSVC at: $vc"; $hasVC = $true }
}
if (-not $hasVC) {
    Write-Host "  [*] downloading vs_BuildTools.exe" -ForegroundColor Cyan
    $boot = "$env:TEMP\vs_BuildTools.exe"
    try { Invoke-WebRequest -Uri "https://aka.ms/vs/17/release/vs_BuildTools.exe" -OutFile $boot -UseBasicParsing }
    catch { Err "download failed: $_"; exit 1 }
    Write-Host "  [*] installing MSVC workload (5-15 min)" -ForegroundColor Cyan
    $args = @("--quiet","--wait","--norestart","--nocache",
              "--add","Microsoft.VisualStudio.Workload.VCTools",
              "--add","Microsoft.VisualStudio.Component.Windows11SDK.22621",
              "--includeRecommended")
    $p = Start-Process -FilePath $boot -ArgumentList $args -Wait -PassThru
    if ($p.ExitCode -notin 0,3010) { Err "installer exit $($p.ExitCode)"; exit 1 }
    Remove-Item $boot -ErrorAction SilentlyContinue
    Ok "MSVC installed"
}

Head "3. CUDA Toolkit (skip on non-NVIDIA)"
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $nvcc = Get-Command nvcc -ErrorAction SilentlyContinue
    if ($nvcc) {
        Ok "nvcc present: $($nvcc.Source)"
    } else {
        Write-Host "  [*] installing CUDA 12.4 via winget" -ForegroundColor Cyan
        winget install --id Nvidia.CUDA --version 12.4 -e --silent --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
        Refresh-Path
        if (Test-Path "$env:ProgramFiles\NVIDIA GPU Computing Toolkit\CUDA\v12.4\bin\nvcc.exe") {
            Ok "CUDA 12.4 installed"
        } else {
            Warn "CUDA 12.4 install incomplete. run install_cuda.ps1 as admin or grab it manually:"
            Write-Host "    https://developer.nvidia.com/cuda-12-4-0-download-archive" -ForegroundColor DarkGray
        }
    }
} else {
    Warn "no NVIDIA GPU; skipping CUDA"
}

Head "4. Ollama (optional)"
if (Have ollama) {
    Ok "ollama present"
} elseif ((Read-Host "  install ollama? [y/N]") -match '^[Yy]') {
    Write-Host "  [*] downloading ollama installer" -ForegroundColor Cyan
    $o = "$env:TEMP\OllamaSetup.exe"
    try {
        Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $o -UseBasicParsing
        Start-Process -FilePath $o -ArgumentList "/silent" -Wait
        Remove-Item $o -ErrorAction SilentlyContinue
        Ok "ollama installed"
    } catch { Warn "ollama install failed: $_" }
} else { Warn "skipping ollama" }

Head "5. PrismML fork (ternary kernels for Bonsai 2)"
& python $CsPy install prism-fork

Head "6. initial setup (runtimes + scan + cs command)"
& python $CsPy setup --quiet

Head "7. verify"
& python $CsPy selftest
& python $CsPy doctor

Write-Host "`n=== DONE ===" -ForegroundColor Green
Write-Host "  open a new PowerShell and run: cs" -ForegroundColor Cyan