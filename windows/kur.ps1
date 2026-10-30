# Trafyle Windows kurulumu (Kur.bat bu dosyayı çalıştırır).
# 1) Python 3.12'yi bulur (yoksa kurmayı önerir)
# 2) Sanal ortamı kurar ve kütüphaneleri yükler
# 3) Başlat menüsüne ve isteğe bağlı olarak masaüstüne Trafyle kısayolu ekler
$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location -LiteralPath $Root
$Host.UI.RawUI.WindowTitle = 'Trafyle kurulumu'

function Bold($m) { Write-Host $m -ForegroundColor Cyan }
function Fail($m) {
    Write-Host ""
    Write-Host $m -ForegroundColor Red
    Write-Host ""
    Read-Host "Kapatmak için Enter'a basın" | Out-Null
    exit 1
}

Clear-Host
Bold 'Trafyle kurulumu'
Write-Host "Klasör: $Root"
Write-Host ''

# İnternetten indirilen dosyaların "engellendi" işaretini kaldır
Get-ChildItem -LiteralPath $Root -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue

# --- 1. Python (3.12 önerilir; 3.11 ve 3.13 de çalışır)
function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in '3.12', '3.13', '3.11') {
            $p = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { return ($p | Select-Object -First 1).Trim() }
        }
    }
    foreach ($v in '312', '313', '311') {
        foreach ($base in @("$env:LOCALAPPDATA\Programs\Python", "$env:ProgramFiles")) {
            $c = Join-Path $base "Python$v\python.exe"
            if (Test-Path -LiteralPath $c) { return $c }
        }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $a = Read-Host 'Python 3.12 bulunamadı. Şimdi otomatik kurulsun mu? (e/h)'
        if ($a -match '^[eE]') {
            Bold 'Python 3.12 kuruluyor…'
            winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
            $py = Find-Python
        }
    }
    if (-not $py) {
        Start-Process 'https://www.python.org/downloads/windows/'
        Fail ("Python 3.12 gerekli. Açılan sayfadan 'Windows installer (64-bit)' dosyasını indirip kurun " +
              "(ilk ekranda 'Add python.exe to PATH' kutusunu işaretleyin), sonra Kur.bat'a yeniden çift tıklayın.")
    }
}
Write-Host "Python: $py"
& $py -c "import tkinter" 2>$null
if ($LASTEXITCODE -ne 0) {
    Fail "Bu Python'da arayüz kütüphanesi (tkinter) yok. python.org yükleyicisinde 'tcl/tk and IDLE' seçeneğini açık bırakarak yeniden kurun."
}

# --- 2. Sanal ortam ve kütüphaneler
$vpy = Join-Path $Root '.venv\Scripts\python.exe'
$vpyw = Join-Path $Root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $vpy)) {
    Bold 'Sanal ortam oluşturuluyor…'
    & $py -m venv .venv
    if ($LASTEXITCODE -ne 0) { Fail 'Sanal ortam oluşturulamadı.' }
}
Bold 'Kütüphaneler yükleniyor (ilk seferde birkaç dakika sürebilir)…'
& $vpy -m pip install --upgrade pip -q
if ($LASTEXITCODE -ne 0) { Fail 'pip güncellenemedi. İnternet bağlantınızı kontrol edin.' }
& $vpy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Fail "Kütüphaneler yüklenemedi. Hata mesajını Claude'a iletebilirsiniz." }
# Bağlantıdan ses alma bileşeni siteler değiştikçe güncellenmeli
& $vpy -m pip install -U -q yt-dlp yt-dlp-ejs deno
if ($LASTEXITCODE -ne 0) { Write-Host 'Uyarı: bağlantı desteği güncellenemedi; uygulama içinden yeniden deneyebilirsiniz.' -ForegroundColor Yellow }

# --- 3. Kısayollar
Bold 'Kısayollar oluşturuluyor…'
$ws = New-Object -ComObject WScript.Shell
function New-Link($path) {
    $l = $ws.CreateShortcut($path)
    $l.TargetPath = $vpyw
    $l.Arguments = '"' + (Join-Path $Root 'app.py') + '"'
    $l.WorkingDirectory = $Root
    $l.IconLocation = (Join-Path $Root 'assets\AppIcon.ico') + ',0'
    $l.Description = 'Trafyle: ses, metin ve dosya dönüştürücü'
    $l.Save()
}

# Kısayola uygulamanın kimliğini (AppUserModelID) yaz: görev çubuğunda Python yerine Trafyle simgesi
# görünür ve sabitlenen simge ile açık pencere tek düğmede birleşir.
$aumidCode = @"
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IPropertyStore {
    [PreserveSig] int GetCount(out uint c);
    [PreserveSig] int GetAt(uint i, out TrafylePropertyKey k);
    [PreserveSig] int GetValue(ref TrafylePropertyKey k, out TrafylePropVariant v);
    [PreserveSig] int SetValue(ref TrafylePropertyKey k, ref TrafylePropVariant v);
    [PreserveSig] int Commit();
}
[StructLayout(LayoutKind.Sequential, Pack = 4)]
public struct TrafylePropertyKey { public Guid fmtid; public uint pid; }
[StructLayout(LayoutKind.Explicit, Size = 16)]
public struct TrafylePropVariant { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; }
public static class TrafyleAumid {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    static extern int SHGetPropertyStoreFromParsingName(string path, IntPtr pbc, int flags, ref Guid riid,
        [MarshalAs(UnmanagedType.Interface)] out IPropertyStore ps);
    public static void Set(string lnk, string id) {
        Guid iid = new Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99");
        IPropertyStore ps;
        int hr = SHGetPropertyStoreFromParsingName(lnk, IntPtr.Zero, 2, ref iid, out ps);
        if (hr != 0) Marshal.ThrowExceptionForHR(hr);
        TrafylePropertyKey k = new TrafylePropertyKey();
        k.fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"); k.pid = 5;
        TrafylePropVariant v = new TrafylePropVariant();
        v.vt = 31; v.p = Marshal.StringToCoTaskMemUni(id);
        try { ps.SetValue(ref k, ref v); ps.Commit(); }
        finally { Marshal.FreeCoTaskMem(v.p); Marshal.ReleaseComObject(ps); }
    }
}
"@
function Set-AppId($path) {
    try {
        if (-not ('TrafyleAumid' -as [type])) { Add-Type -TypeDefinition $aumidCode -ErrorAction Stop }
        [TrafyleAumid]::Set($path, 'Trafyle.App')
    } catch {
        Write-Host "Not: kısayola uygulama kimliği yazılamadı ($($_.Exception.Message)); Trafyle yine çalışır." -ForegroundColor Yellow
    }
}
# Eski adla (SesMetin) oluşturulmuş kısayolları kaldır
foreach ($old in @((Join-Path ([Environment]::GetFolderPath('Programs')) 'SesMetin.lnk'),
                   (Join-Path ([Environment]::GetFolderPath('Desktop')) 'SesMetin.lnk'))) {
    if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue }
}
$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Trafyle.lnk'
New-Link $startMenu
Set-AppId $startMenu
Write-Host "Başlat menüsü: Trafyle"
$a = Read-Host 'Masaüstüne de kısayol eklensin mi? (e/h)'
if ($a -match '^[eE]') {
    $desk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Trafyle.lnk'
    New-Link $desk
    Set-AppId $desk
    Write-Host 'Masaüstü: Trafyle'
}

Write-Host ''
Bold 'Kurulum tamamlandı.'
Write-Host "Trafyle'ı Başlat menüsünden (Windows tuşu → Trafyle) ya da masaüstü kısayolundan açabilirsiniz."
Write-Host "Görev çubuğuna sabitlemek için: uygulama açıkken görev çubuğundaki Trafyle simgesine sağ tıklayın → 'Görev çubuğuna sabitle'."
Write-Host 'Not: Bu klasörü taşırsanız Kur.bat dosyasına yeniden çift tıklayın.'
Write-Host ''
Start-Process -FilePath $vpyw -ArgumentList ('"' + (Join-Path $Root 'app.py') + '"') -WorkingDirectory $Root
Read-Host 'Bu pencereyi kapatmak için Enter tuşuna basın' | Out-Null
