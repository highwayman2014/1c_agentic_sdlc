param([Parameter(Mandatory=$true)][string]$Source,[switch]$Stop)
$ErrorActionPreference='Stop'
$root=(Resolve-Path -LiteralPath $Source).Path.TrimEnd('\')
$currentSid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$records=@()
Get-CimInstance Win32_Process -Filter "Name LIKE 'bsl-analyzer%'" | ForEach-Object {
    $p=$_
    if ($p.CommandLine -notmatch '--source-dir\s+(?:"([^"]+)"|(\S+))') { return }
    $declared=(($Matches[1]+$Matches[2]) -replace '^\\\\\?\\','').TrimEnd('\')
    if ($declared -ne $root) { return }
    $mode=''
    if ($p.CommandLine -match '--mode\s+(\S+)') { $mode=$Matches[1] }
    if ($mode -eq 'broker' -or $mode -eq 'broker-required') { return }
    $sid=Invoke-CimMethod -InputObject $p -MethodName GetOwnerSid
    $owned=$sid.ReturnValue -eq 0 -and $sid.Sid -eq $currentSid
    $records += [pscustomobject]@{pid=$p.ProcessId;source=$root;mode=$mode;owned=$owned;creation=$p.CreationDate}
}
if ($Stop) {
    if (@($records | Where-Object { !$_.owned -or $_.mode -ne 'daemon' }).Count) { throw 'Unmanaged or foreign source backend exists; no process stopped' }
    foreach ($record in $records) {
        $p=Get-CimInstance Win32_Process -Filter "ProcessId=$($record.pid)"
        if (!$p -or $p.CreationDate -ne $record.creation) { throw 'Backend changed after inspection; no stale PID stop' }
        Stop-Process -Id $record.pid
    }
}
ConvertTo-Json -InputObject @($records | Select-Object pid,source,mode,owned) -Compress
