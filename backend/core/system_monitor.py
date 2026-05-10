from datetime import datetime
from pathlib import Path
import time
import psutil
import json
import subprocess
import heapq


WATCHED_PROCESSES = {
    "Ollama": "ollama.exe",
    "Obsidian": "Obsidian.exe",
    "Discord": "Discord.exe",
    "Opera": "opera.exe",
    "Postgres": "postgres.exe",
}

CACHE_TTL = 2  # segundos para evitar recalcular métricas toda hora

_metrics_cache = {
    "timestamp": 0,
    "data": None,
}


def _bytes_to_gb(value: int | float) -> float:
    return round(value / (1024 ** 3), 2)


def _get_disk_path() -> str:
    """
    Retorna o disco principal de forma segura.
    No Windows, normalmente será C:\\.
    Em Linux/Mac, será /.
    """
    if Path("C:\\").exists():
        return "C:\\"

    return "/"


def _is_reparse_point(path: Path) -> bool:
    """
    Evita seguir junctions, symlinks e atalhos especiais do Windows.
    Isso impede contagem duplicada e loops em pastas como All Users.
    """
    try:
        return path.is_symlink() or bool(path.stat().st_file_attributes & 0x400)
    except Exception:
        return False


def _safe_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except (OSError, PermissionError):
        return False


def _safe_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except (OSError, PermissionError):
        return False


def _get_running_processes() -> set[str]:
    """
    Lê todos os processos uma única vez.
    Isso é mais eficiente do que procurar processo por processo.
    """
    running = set()

    for process in psutil.process_iter(["name"]):
        try:
            name = process.info.get("name")

            if name:
                running.add(name.lower())

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return running


def _get_watched_processes_status() -> dict:
    running_processes = _get_running_processes()

    return {
        app_name: process_name.lower() in running_processes
        for app_name, process_name in WATCHED_PROCESSES.items()
    }


def get_storage_devices() -> list[dict]:
    """
    Busca os dispositivos físicos de armazenamento no Windows.

    Retorna separado:
    - NVMe
    - SSD
    - HDD

    Também tenta associar volumes/letras como C:, D:, E: etc.
    """
    powershell_script = r"""
    $devices = Get-PhysicalDisk | ForEach-Object {
        $physical = $_
        $disk = Get-Disk -Number $physical.DeviceId -ErrorAction SilentlyContinue

        $volumes = @()

        if ($disk) {
            $partitions = Get-Partition -DiskNumber $disk.Number -ErrorAction SilentlyContinue

            foreach ($partition in $partitions) {
                $volume = $partition | Get-Volume -ErrorAction SilentlyContinue

                if ($volume -and $volume.DriveLetter) {
                    $volumes += [PSCustomObject]@{
                        drive_letter = "$($volume.DriveLetter):"
                        label = $volume.FileSystemLabel
                        file_system = $volume.FileSystem
                        size_gb = [math]::Round($volume.Size / 1GB, 2)
                        free_gb = [math]::Round($volume.SizeRemaining / 1GB, 2)
                        used_percent = if ($volume.Size -gt 0) {
                            [math]::Round((($volume.Size - $volume.SizeRemaining) / $volume.Size) * 100, 2)
                        } else {
                            0
                        }
                    }
                }
            }
        }

        [PSCustomObject]@{
            name = $physical.FriendlyName
            media_type = "$($physical.MediaType)"
            bus_type = "$($physical.BusType)"
            health_status = "$($physical.HealthStatus)"
            operational_status = "$($physical.OperationalStatus)"
            size_gb = [math]::Round($physical.Size / 1GB, 2)
            volumes = $volumes
        }
    }

    $devices | ConvertTo-Json -Depth 6
    """

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                powershell_script,
            ],
            capture_output=True,
            text=True,
            timeout=8,
            encoding="utf-8",
            errors="ignore",
        )

        if result.returncode != 0 or not result.stdout.strip():
            return []

        data = json.loads(result.stdout)

        if isinstance(data, dict):
            data = [data]

        devices = []

        for device in data:
            media_type = str(device.get("media_type", "")).upper()
            bus_type = str(device.get("bus_type", "")).upper()

            if bus_type == "NVME":
                kind = "NVMe"
            elif media_type == "HDD":
                kind = "HDD"
            elif media_type == "SSD":
                kind = "SSD"
            else:
                kind = "Desconhecido"

            volumes = device.get("volumes") or []

            if isinstance(volumes, dict):
                volumes = [volumes]

            devices.append(
                {
                    "name": device.get("name"),
                    "media_type": device.get("media_type"),
                    "bus_type": device.get("bus_type"),
                    "kind": kind,
                    "health_status": device.get("health_status"),
                    "operational_status": device.get("operational_status"),
                    "size_gb": device.get("size_gb"),
                    "volumes": volumes,
                }
            )

        return devices

    except Exception as exc:
        print(f"Erro ao buscar dispositivos de armazenamento: {exc}")
        return []


def get_system_metrics() -> dict:
    current_time = time.time()

    if (
        _metrics_cache["data"] is not None
        and current_time - _metrics_cache["timestamp"] < CACHE_TTL
    ):
        return _metrics_cache["data"]

    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(_get_disk_path())
    boot_time = datetime.fromtimestamp(psutil.boot_time())

    data = {
        "cpu": {
            "percent": psutil.cpu_percent(interval=0.1),
            "cores_physical": psutil.cpu_count(logical=False),
            "cores_logical": psutil.cpu_count(logical=True),
        },
        "memory": {
            "percent": memory.percent,
            "used_gb": _bytes_to_gb(memory.used),
            "total_gb": _bytes_to_gb(memory.total),
            "available_gb": _bytes_to_gb(memory.available),
        },
        "disk": {
            "percent": disk.percent,
            "used_gb": _bytes_to_gb(disk.used),
            "total_gb": _bytes_to_gb(disk.total),
            "free_gb": _bytes_to_gb(disk.free),
        },
        "storage_devices": get_storage_devices(),
        "processes": _get_watched_processes_status(),
        "uptime": {
            "boot_time": boot_time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    _metrics_cache["timestamp"] = current_time
    _metrics_cache["data"] = data

    return data


def analyze_system_health(metrics: dict) -> dict:
    alerts = []
    recommendations = []

    cpu = metrics.get("cpu", {})
    memory = metrics.get("memory", {})
    disk = metrics.get("disk", {})
    storage_devices = metrics.get("storage_devices", [])
    processes = metrics.get("processes", {})

    cpu_percent = cpu.get("percent", 0)
    memory_percent = memory.get("percent", 0)
    disk_percent = disk.get("percent", 0)

    status = "good"

    if cpu_percent >= 90:
        status = "critical"
        alerts.append("CPU em uso muito alto.")
        recommendations.append("Verifique processos pesados ou travados.")
    elif cpu_percent >= 75:
        if status != "critical":
            status = "warning"
        alerts.append("CPU em uso elevado.")
        recommendations.append("Evite abrir tarefas pesadas ao mesmo tempo.")

    if memory_percent >= 90:
        status = "critical"
        alerts.append("Memória RAM em nível crítico.")
        recommendations.append(
            "Feche programas pesados ou evite iniciar Ollama/modelos locais agora."
        )
    elif memory_percent >= 75:
        if status != "critical":
            status = "warning"
        alerts.append("Memória RAM em uso alto.")
        recommendations.append(
            "Monitore navegador, Discord, Obsidian, Postgres e possíveis modelos locais."
        )

    if disk_percent >= 90:
        status = "critical"
        alerts.append("Disco principal está quase cheio.")
        recommendations.append(
            "Libere espaço no disco C:. Idealmente deixe pelo menos 30 a 50 GB livres."
        )
    elif disk_percent >= 80:
        if status != "critical":
            status = "warning"
        alerts.append("Disco principal está com uso elevado.")
        recommendations.append("Comece uma limpeza preventiva no disco principal.")

    storage_summary = []

    for device in storage_devices:
        kind = device.get("kind", "Desconhecido")
        name = device.get("name", "Dispositivo desconhecido")
        health = device.get("health_status", "Unknown")
        bus = device.get("bus_type", "Unknown")
        volumes = device.get("volumes", [])

        device_status = "good"
        device_alerts = []

        if str(health).lower() != "healthy":
            device_status = "warning"
            alerts.append(f"{kind} {name} não está marcado como saudável.")
            device_alerts.append(f"Saúde reportada: {health}")

        for volume in volumes:
            drive = volume.get("drive_letter", "?")
            used_percent = volume.get("used_percent", 0)
            free_gb = volume.get("free_gb", 0)

            if used_percent >= 90:
                device_status = "critical"
                status = "critical"
                alerts.append(f"Unidade {drive} está quase cheia: {used_percent}% usado.")
                recommendations.append(
                    f"Libere espaço na unidade {drive}. Espaço livre atual: {free_gb} GB."
                )
                device_alerts.append(f"{drive} crítico: {used_percent}% usado.")

            elif used_percent >= 80:
                if device_status != "critical":
                    device_status = "warning"
                if status != "critical":
                    status = "warning"
                alerts.append(f"Unidade {drive} está com uso elevado: {used_percent}% usado.")
                recommendations.append(f"Considere limpar ou mover arquivos da unidade {drive}.")
                device_alerts.append(f"{drive} alto uso: {used_percent}% usado.")

        storage_summary.append(
            {
                "name": name,
                "kind": kind,
                "bus_type": bus,
                "health_status": health,
                "status": device_status,
                "volumes": volumes,
                "alerts": device_alerts,
            }
        )

    running_processes = [
        name for name, is_running in processes.items() if is_running
    ]

    stopped_processes = [
        name for name, is_running in processes.items() if not is_running
    ]

    if processes.get("Ollama") and memory_percent >= 70:
        if status != "critical":
            status = "warning"
        alerts.append("Ollama está aberto com RAM relativamente alta.")
        recommendations.append(
            "Se o PC ficar pesado, considere fechar o Ollama quando não estiver usando."
        )

    if processes.get("Postgres"):
        recommendations.append(
            "Postgres está ativo. Isso é esperado para o Helix, mas consome recursos em segundo plano."
        )

    if not alerts:
        summary = "O PC parece saudável no momento."
    elif status == "critical":
        summary = "O PC tem pontos críticos que merecem atenção."
    else:
        summary = "O PC está funcional, mas há pontos de atenção."

    return {
        "status": status,
        "summary": summary,
        "alerts": alerts,
        "recommendations": recommendations,
        "storage_summary": storage_summary,
        "running_processes": running_processes,
        "stopped_processes": stopped_processes,
        "raw_metrics": metrics,
    }


def get_system_diagnostic() -> dict:
    metrics = get_system_metrics()
    return analyze_system_health(metrics)


def get_hardware_info() -> dict:
    powershell_script = r"""
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
    $gpus = Get-CimInstance Win32_VideoController
    $ram = Get-CimInstance Win32_PhysicalMemory
    $board = Get-CimInstance Win32_BaseBoard | Select-Object -First 1
    $bios = Get-CimInstance Win32_BIOS | Select-Object -First 1
    $os = Get-CimInstance Win32_OperatingSystem | Select-Object -First 1
    $computer = Get-CimInstance Win32_ComputerSystem | Select-Object -First 1

    $ramModules = @()
    foreach ($module in $ram) {
        $ramModules += [PSCustomObject]@{
            manufacturer = $module.Manufacturer
            part_number = $module.PartNumber
            capacity_gb = [math]::Round($module.Capacity / 1GB, 2)
            speed_mhz = $module.Speed
            configured_speed_mhz = $module.ConfiguredClockSpeed
            bank = $module.BankLabel
            slot = $module.DeviceLocator
        }
    }

    $gpuList = @()
    foreach ($gpu in $gpus) {
        $gpuList += [PSCustomObject]@{
            name = $gpu.Name
            adapter_ram_gb = if ($gpu.AdapterRAM) {
                [math]::Round($gpu.AdapterRAM / 1GB, 2)
            } else {
                $null
            }
            driver_version = $gpu.DriverVersion
            video_processor = $gpu.VideoProcessor
        }
    }

    [PSCustomObject]@{
        cpu = [PSCustomObject]@{
            name = $cpu.Name
            manufacturer = $cpu.Manufacturer
            cores = $cpu.NumberOfCores
            logical_processors = $cpu.NumberOfLogicalProcessors
            max_clock_mhz = $cpu.MaxClockSpeed
        }

        gpu = $gpuList

        memory = [PSCustomObject]@{
            total_gb = [math]::Round($computer.TotalPhysicalMemory / 1GB, 2)
            modules = $ramModules
        }

        motherboard = [PSCustomObject]@{
            manufacturer = $board.Manufacturer
            product = $board.Product
            serial_number = $board.SerialNumber
        }

        bios = [PSCustomObject]@{
            manufacturer = $bios.Manufacturer
            version = $bios.SMBIOSBIOSVersion
            release_date = $bios.ReleaseDate
        }

        operating_system = [PSCustomObject]@{
            name = $os.Caption
            version = $os.Version
            build_number = $os.BuildNumber
            architecture = $os.OSArchitecture
        }

        computer = [PSCustomObject]@{
            manufacturer = $computer.Manufacturer
            model = $computer.Model
            system_type = $computer.SystemType
        }
    } | ConvertTo-Json -Depth 8
    """

    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                powershell_script,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="ignore",
        )

        if result.returncode != 0 or not result.stdout.strip():
            return {
                "available": False,
                "error": result.stderr.strip() or "Não foi possível ler o hardware.",
            }

        data = json.loads(result.stdout)

        return {
            "available": True,
            **data,
        }

    except Exception as exc:
        return {
            "available": False,
            "error": str(exc),
        }


def _get_folder_size(
    path: Path,
    max_files: int = 5000,
    max_seconds: float = 2.5,
) -> dict:
    total_size = 0
    file_count = 0
    skipped = 0
    stopped_early = False
    start_time = time.time()

    if not path.exists():
        return {
            "exists": False,
            "size_gb": 0,
            "file_count": 0,
            "skipped": 0,
            "stopped_early": False,
            "error": "Pasta não encontrada.",
        }

    try:
        for item in path.rglob("*"):
            if file_count >= max_files:
                stopped_early = True
                break

            if time.time() - start_time >= max_seconds:
                stopped_early = True
                break

            try:
                if _is_reparse_point(item):
                    skipped += 1
                    continue

                if item.is_file():
                    total_size += item.stat().st_size
                    file_count += 1
            except (OSError, PermissionError):
                skipped += 1

        return {
            "exists": True,
            "size_gb": _bytes_to_gb(total_size),
            "file_count": file_count,
            "skipped": skipped,
            "stopped_early": stopped_early,
            "error": None,
        }

    except (OSError, PermissionError) as exc:
        return {
            "exists": True,
            "size_gb": _bytes_to_gb(total_size),
            "file_count": file_count,
            "skipped": skipped,
            "stopped_early": stopped_early,
            "error": str(exc),
        }


def _classify_storage_folder(name: str, path: Path, size_gb: float) -> dict:
    path_text = str(path).lower()

    if "windows" in path_text or "program files" in path_text:
        return {
            "risk": "high",
            "category": "system",
            "suggestion": "Não apagar manualmente. Pasta de sistema ou programas.",
        }

    if "temp" in path_text:
        return {
            "risk": "medium",
            "category": "cache",
            "suggestion": "Pode conter arquivos temporários, mas revisar antes de limpar.",
        }

    if name.lower() in ["downloads", "desktop", "vídeos", "videos", "pictures", "imagens"]:
        return {
            "risk": "low",
            "category": "user_files",
            "suggestion": "Boa candidata para revisão manual, mover ou apagar arquivos antigos.",
        }

    if size_gb >= 10:
        return {
            "risk": "medium",
            "category": "large_folder",
            "suggestion": "Pasta grande. Revisar conteúdo antes de qualquer ação.",
        }

    return {
        "risk": "low",
        "category": "general",
        "suggestion": "Sem alerta forte. Revisar apenas se precisar liberar espaço.",
    }


def scan_storage_usage() -> dict:
    user_profile = Path.home()

    folders_to_scan = [
        {"name": "Downloads", "path": user_profile / "Downloads"},
        {"name": "Desktop", "path": user_profile / "Desktop"},
        {"name": "Documents", "path": user_profile / "Documents"},
        {"name": "Pictures", "path": user_profile / "Pictures"},
        {"name": "Videos", "path": user_profile / "Videos"},
        {"name": "User Temp", "path": Path.home() / "AppData" / "Local" / "Temp"},
        {"name": "Windows Temp", "path": Path("C:/Windows/Temp")},
    ]

    results = []

    for folder in folders_to_scan:
        path = folder["path"]
        size_info = _get_folder_size(path)

        classification = _classify_storage_folder(
            name=folder["name"],
            path=path,
            size_gb=size_info["size_gb"],
        )

        results.append(
            {
                "name": folder["name"],
                "path": str(path),
                **size_info,
                **classification,
            }
        )

    results.sort(key=lambda item: item["size_gb"], reverse=True)

    total_scanned_gb = round(
        sum(item["size_gb"] for item in results if item["exists"]),
        2,
    )

    alerts = []
    recommendations = []

    for item in results:
        if not item["exists"]:
            continue

        if item["size_gb"] >= 10:
            alerts.append(
                f"{item['name']} está grande: {item['size_gb']} GB."
            )

        if item["category"] == "user_files" and item["size_gb"] >= 5:
            recommendations.append(
                f"Revisar {item['name']}: pode ter arquivos antigos para mover para o D: ou E:."
            )

        if item["category"] == "cache" and item["size_gb"] >= 3:
            recommendations.append(
                f"Revisar {item['name']}: pode conter temporários acumulados."
            )

    return {
        "mode": "safe_scan_only",
        "message": "Scanner seguro executado. Nenhum arquivo foi apagado.",
        "total_scanned_gb": total_scanned_gb,
        "folders": results,
        "alerts": alerts,
        "recommendations": recommendations,
    }


def _classify_drive_root_folder(name: str, path: Path, size_gb: float) -> dict:
    name_lower = name.lower()

    if name_lower in ["windows", "$windows.~bt", "$winreagent"]:
        return {
            "risk": "high",
            "category": "system",
            "suggestion": "Pasta de sistema. Não apagar manualmente.",
        }

    if name_lower in ["program files", "program files (x86)"]:
        return {
            "risk": "high",
            "category": "programs",
            "suggestion": "Contém programas instalados. Desinstale pelo Windows, não apague a pasta manualmente.",
        }

    if name_lower in ["programdata"]:
        return {
            "risk": "high",
            "category": "program_data",
            "suggestion": "Contém dados de programas. Revisar com cuidado; não apagar manualmente.",
        }

    if name_lower in ["users", "usuários", "usuarios"]:
        return {
            "risk": "medium",
            "category": "user_data",
            "suggestion": "Provável local de arquivos pessoais, AppData, caches e projetos. Bom candidato para análise detalhada.",
        }

    if name_lower in ["temp", "tmp"]:
        return {
            "risk": "medium",
            "category": "cache",
            "suggestion": "Pode conter temporários. Revisar antes de limpar.",
        }

    if size_gb >= 10:
        return {
            "risk": "medium",
            "category": "large_folder",
            "suggestion": "Pasta grande. Investigar antes de qualquer ação.",
        }

    return {
        "risk": "low",
        "category": "general",
        "suggestion": "Sem alerta forte. Revisar apenas se necessário.",
    }


def scan_drive_top_level(
    drive_path: str = "C:/",
    max_files_per_folder: int = 5000,
) -> dict:
    drive = Path(drive_path)

    if not drive.exists():
        return {
            "mode": "safe_scan_only",
            "error": f"Unidade não encontrada: {drive_path}",
            "folders": [],
        }

    results = []

    try:
        items = [
            item for item in drive.iterdir()
            if item.is_dir() and not _is_reparse_point(item)
        ]
    except (OSError, PermissionError) as exc:
        return {
            "mode": "safe_scan_only",
            "error": str(exc),
            "folders": [],
        }

    for folder in items:
        size_info = _get_folder_size(
            folder,
            max_files=max_files_per_folder,
            max_seconds=2.5,
        )

        classification = _classify_drive_root_folder(
            name=folder.name,
            path=folder,
            size_gb=size_info.get("size_gb", 0),
        )

        results.append(
            {
                "name": folder.name,
                "path": str(folder),
                **size_info,
                **classification,
            }
        )

    results.sort(key=lambda item: item.get("size_gb", 0), reverse=True)

    alerts = []
    recommendations = []

    for item in results:
        size_gb = item.get("size_gb", 0)

        if item.get("stopped_early"):
            recommendations.append(
                f"{item['path']} é grande demais para escanear completamente agora. Resultado aproximado."
            )

        if size_gb >= 20:
            alerts.append(
                f"{item['path']} ocupou pelo menos {size_gb} GB dentro do limite analisado."
            )

        if item.get("category") == "user_data":
            recommendations.append(
                f"Investigar {item['path']}. Geralmente é onde ficam AppData, OneDrive, Downloads e projetos."
            )

        if item.get("category") == "programs":
            recommendations.append(
                f"Revisar programas instalados em {item['path']} pelo desinstalador do Windows, não apagando manualmente."
            )

        if item.get("category") == "system":
            recommendations.append(
                f"Evitar apagar manualmente {item['path']}. Use ferramentas do Windows se precisar limpar."
            )

    return {
        "mode": "safe_scan_only",
        "message": "Scanner seguro da raiz do disco executado. Nenhum arquivo foi apagado.",
        "drive": str(drive),
        "folders": results,
        "alerts": alerts,
        "recommendations": recommendations,
        "total_scanned_gb": round(
            sum(item.get("size_gb", 0) for item in results if item.get("exists")),
            2,
        ),
        "note": "Os tamanhos podem ser aproximados quando stopped_early=true.",
    }


def _classify_any_folder(path: Path, size_gb: float) -> dict:
    path_text = str(path).lower()
    name = path.name.lower()

    if "\\windows" in path_text or "/windows" in path_text:
        return {
            "risk": "high",
            "category": "system",
            "suggestion": "Pasta de sistema. Não apagar manualmente. Use ferramentas do Windows.",
        }

    if "program files" in path_text:
        return {
            "risk": "high",
            "category": "programs",
            "suggestion": "Contém programas instalados. Use o desinstalador do Windows.",
        }

    if "programdata" in path_text:
        return {
            "risk": "high",
            "category": "program_data",
            "suggestion": "Dados de programas. Revisar com muito cuidado.",
        }

    if "appdata" in path_text:
        return {
            "risk": "medium",
            "category": "app_cache",
            "suggestion": "Pode conter cache e dados de aplicativos. Investigar antes de apagar.",
        }

    if name in ["downloads", "desktop", "videos", "vídeos", "pictures", "imagens"]:
        return {
            "risk": "low",
            "category": "user_files",
            "suggestion": "Boa candidata para revisão manual ou mover arquivos para D: ou E:.",
        }

    if "temp" in path_text or "cache" in path_text:
        return {
            "risk": "medium",
            "category": "cache",
            "suggestion": "Pode conter temporários/cache. Revisar antes de limpar.",
        }

    if size_gb >= 10:
        return {
            "risk": "medium",
            "category": "large_folder",
            "suggestion": "Pasta grande. Investigar conteúdo antes de qualquer ação.",
        }

    return {
        "risk": "low",
        "category": "general",
        "suggestion": "Sem alerta forte. Revisar apenas se necessário.",
    }


def scan_storage_map(
    root_path: str = "C:/",
    max_depth: int = 2,
    max_children_per_folder: int = 30,
    max_files_per_folder: int = 3000,
    min_size_gb: float = 0.5,
) -> dict:
    root = Path(root_path)

    if not root.exists():
        return {
            "mode": "safe_general_scan",
            "error": f"Caminho não encontrado: {root_path}",
            "folders": [],
        }

    found_folders = []

    def scan_level(current_path: Path, depth: int):
        if depth > max_depth:
            return

        try:
            children = [
                item for item in current_path.iterdir()
                if item.is_dir() and not _is_reparse_point(item)
            ]
        except (OSError, PermissionError):
            return

        children = children[:max_children_per_folder]

        for child in children:
            size_info = _get_folder_size(
                child,
                max_files=max_files_per_folder,
                max_seconds=1.5,
            )

            size_gb = size_info.get("size_gb", 0)

            if size_gb >= min_size_gb or size_info.get("stopped_early"):
                classification = _classify_any_folder(child, size_gb)

                found_folders.append(
                    {
                        "name": child.name,
                        "path": str(child),
                        "depth": depth,
                        **size_info,
                        **classification,
                    }
                )

            path_text = str(child).lower()
            blocked_deep_scan = (
                "\\windows" in path_text
                or "/windows" in path_text
                or "program files" in path_text
            )

            if not blocked_deep_scan:
                scan_level(child, depth + 1)

    scan_level(root, 1)

    found_folders.sort(
        key=lambda item: (
            item.get("size_gb", 0),
            1 if item.get("stopped_early") else 0,
        ),
        reverse=True,
    )

    alerts = []
    recommendations = []

    for item in found_folders[:20]:
        size_gb = item.get("size_gb", 0)
        path = item.get("path")

        if item.get("stopped_early"):
            recommendations.append(
                f"{path} parece grande, mas foi interrompida por segurança. Resultado aproximado."
            )

        if size_gb >= 5:
            alerts.append(f"{path} ocupa pelo menos {size_gb} GB.")

        if item.get("risk") == "low" and size_gb >= 1:
            recommendations.append(
                f"{path} parece mais segura para revisão manual ou mover arquivos."
            )

        if item.get("risk") == "high":
            recommendations.append(
                f"{path} é sensível. Não apagar manualmente."
            )

    return {
        "mode": "safe_general_scan",
        "message": "Scanner geral executado. Nenhum arquivo foi apagado.",
        "root": str(root),
        "max_depth": max_depth,
        "min_size_gb": min_size_gb,
        "folders_found": len(found_folders),
        "largest_folders": found_folders[:30],
        "alerts": alerts,
        "recommendations": recommendations,
        "note": "Os tamanhos podem ser aproximados quando stopped_early=true.",
    }


def _classify_root_file(path: Path, size_gb: float) -> dict:
    name = path.name.lower()

    if name == "pagefile.sys":
        return {
            "risk": "high",
            "category": "virtual_memory",
            "suggestion": (
                "Arquivo de memória virtual do Windows. Não apagar manualmente. "
                "Pode ser ajustado pelas configurações avançadas do sistema."
            ),
        }

    if name == "hiberfil.sys":
        return {
            "risk": "medium",
            "category": "hibernation",
            "suggestion": (
                "Arquivo de hibernação do Windows. Pode ser removido desativando a hibernação "
                "com comando apropriado, mas não apague manualmente."
            ),
        }

    if name == "swapfile.sys":
        return {
            "risk": "high",
            "category": "system_swap",
            "suggestion": "Arquivo de swap do Windows. Não apagar manualmente.",
        }

    if path.suffix.lower() in [".log", ".tmp", ".bak", ".old"]:
        return {
            "risk": "medium",
            "category": "temporary_or_backup",
            "suggestion": "Pode ser temporário ou backup. Revisar origem antes de apagar.",
        }

    if size_gb >= 1:
        return {
            "risk": "medium",
            "category": "large_file",
            "suggestion": "Arquivo grande na raiz do disco. Investigar antes de qualquer ação.",
        }

    return {
        "risk": "low",
        "category": "general",
        "suggestion": "Arquivo comum. Sem alerta forte.",
    }


def scan_drive_root_files(
    drive_path: str = "C:/",
    min_size_gb: float = 0.1,
) -> dict:
    drive = Path(drive_path)

    if not drive.exists():
        return {
            "mode": "safe_scan_only",
            "error": f"Unidade não encontrada: {drive_path}",
            "files": [],
        }

    files = []

    try:
        items = [item for item in drive.iterdir() if item.is_file()]
    except (OSError, PermissionError) as exc:
        return {
            "mode": "safe_scan_only",
            "error": str(exc),
            "files": [],
        }

    for file_path in items:
        try:
            size_bytes = file_path.stat().st_size
            size_gb = _bytes_to_gb(size_bytes)
        except (OSError, PermissionError):
            continue

        if size_gb < min_size_gb:
            continue

        classification = _classify_root_file(file_path, size_gb)

        files.append(
            {
                "name": file_path.name,
                "path": str(file_path),
                "size_gb": size_gb,
                **classification,
            }
        )

    files.sort(key=lambda item: item.get("size_gb", 0), reverse=True)

    alerts = []
    recommendations = []

    for item in files:
        path = item.get("path")
        size_gb = item.get("size_gb")
        category = item.get("category")

        if size_gb >= 1:
            alerts.append(f"{path} ocupa {size_gb} GB.")

        if category == "hibernation":
            recommendations.append(
                "Se você não usa hibernação, pode liberar espaço desativando a hibernação pelo Windows."
            )

        if category == "virtual_memory":
            recommendations.append(
                "O pagefile.sys pode ser grande. Não apague; ajuste apenas pelas configurações do Windows se necessário."
            )

        if category in ["system_swap", "virtual_memory"]:
            recommendations.append(f"Não apagar manualmente {path}.")

    return {
        "mode": "safe_scan_only",
        "message": "Scanner de arquivos grandes da raiz executado. Nenhum arquivo foi apagado.",
        "drive": str(drive),
        "min_size_gb": min_size_gb,
        "files_found": len(files),
        "files": files,
        "alerts": alerts,
        "recommendations": recommendations,
    }


def evaluate_storage_audit(
    metrics: dict,
    drive_scan: dict,
    storage_map: dict,
    root_files: dict,
) -> dict:
    alerts = []
    recommendations = []
    safe_candidates = []
    risky_candidates = []

    disk = metrics.get("disk", {})
    storage_devices = metrics.get("storage_devices", [])

    disk_percent = disk.get("percent", 0)
    disk_free_gb = disk.get("free_gb", 0)

    status = "good"

    if disk_percent >= 90:
        status = "critical"
        alerts.append(
            f"O disco principal está crítico: {disk_percent}% usado, apenas {disk_free_gb} GB livres."
        )
        recommendations.append(
            "Prioridade alta: liberar espaço no C:. Idealmente deixar pelo menos 30 a 50 GB livres."
        )
    elif disk_percent >= 80:
        status = "warning"
        alerts.append(
            f"O disco principal está com uso alto: {disk_percent}% usado."
        )
        recommendations.append(
            "Recomendado iniciar limpeza preventiva no C:."
        )

    largest_folders = storage_map.get("largest_folders", [])

    for folder in largest_folders:
        path = folder.get("path")
        size_gb = folder.get("size_gb", 0)
        risk = folder.get("risk")
        category = folder.get("category")
        suggestion = folder.get("suggestion")
        stopped_early = folder.get("stopped_early")

        item = {
            "path": path,
            "size_gb": size_gb,
            "risk": risk,
            "category": category,
            "stopped_early": stopped_early,
            "suggestion": suggestion,
        }

        if risk == "high":
            risky_candidates.append(item)
        else:
            safe_candidates.append(item)

        if size_gb >= 2 and risk != "high":
            recommendations.append(
                f"Investigar {path}: ocupa pelo menos {size_gb} GB e parece mais seguro para revisão."
            )

        if risk == "high" and size_gb >= 2:
            recommendations.append(
                f"Não apagar manualmente {path}. É sensível; use desinstalador, limpeza de disco ou ferramenta oficial."
            )

    root_big_files = root_files.get("files", [])

    for file_item in root_big_files:
        path = file_item.get("path")
        size_gb = file_item.get("size_gb", 0)
        category = file_item.get("category")
        risk = file_item.get("risk")
        suggestion = file_item.get("suggestion")

        if size_gb >= 1:
            alerts.append(f"Arquivo grande encontrado: {path} com {size_gb} GB.")

        if category == "hibernation":
            recommendations.append(
                "Se você não usa hibernação, pode liberar espaço desativando a hibernação pelo Windows. Não apague hiberfil.sys manualmente."
            )

        if category in ["virtual_memory", "system_swap"]:
            recommendations.append(
                f"{path} é arquivo do sistema/memória virtual. Não apagar manualmente."
            )

        item = {
            "path": path,
            "size_gb": size_gb,
            "risk": risk,
            "category": category,
            "suggestion": suggestion,
        }

        if risk == "high":
            risky_candidates.append(item)
        else:
            safe_candidates.append(item)

    storage_summary = []

    for device in storage_devices:
        device_info = {
            "kind": device.get("kind"),
            "name": device.get("name"),
            "bus_type": device.get("bus_type"),
            "health_status": device.get("health_status"),
            "size_gb": device.get("size_gb"),
            "volumes": device.get("volumes", []),
        }

        storage_summary.append(device_info)

        for volume in device.get("volumes", []):
            drive = volume.get("drive_letter")
            used_percent = volume.get("used_percent", 0)
            free_gb = volume.get("free_gb", 0)

            if used_percent >= 90:
                alerts.append(
                    f"Unidade {drive} está quase cheia: {used_percent}% usado, {free_gb} GB livres."
                )

    recommendations = list(dict.fromkeys(recommendations))
    alerts = list(dict.fromkeys(alerts))

    if status == "critical":
        summary = (
            "O C: está em estado crítico de espaço. O scanner encontrou alguns candidatos, "
            "mas a limpeza deve ser feita com cuidado porque várias áreas são sensíveis."
        )
    elif status == "warning":
        summary = (
            "O C: está com uso alto. Ainda não é emergência total, mas vale limpar antes que piore."
        )
    else:
        summary = "O armazenamento parece saudável no momento."

    return {
        "status": status,
        "summary": summary,
        "alerts": alerts,
        "recommendations": recommendations,
        "safe_candidates": safe_candidates[:15],
        "risky_candidates": risky_candidates[:15],
        "storage_summary": storage_summary,
    }


def scan_full_storage_audit(
    drive_path: str = "C:/",
    max_depth: int = 2,
    min_size_gb: float = 0.5,
) -> dict:
    metrics = get_system_metrics()

    drive_scan = scan_drive_top_level(
        drive_path=drive_path,
        max_files_per_folder=5000,
    )

    storage_map = scan_storage_map(
        root_path=drive_path,
        max_depth=max_depth,
        max_children_per_folder=30,
        max_files_per_folder=3000,
        min_size_gb=min_size_gb,
    )

    root_files = scan_drive_root_files(
        drive_path=drive_path,
        min_size_gb=0.1,
    )

    evaluation = evaluate_storage_audit(
        metrics=metrics,
        drive_scan=drive_scan,
        storage_map=storage_map,
        root_files=root_files,
    )

    return {
        "mode": "safe_full_storage_audit",
        "message": "Auditoria geral de armazenamento executada. Nenhum arquivo foi apagado.",
        "drive": drive_path,
        "evaluation": evaluation,
        "drive_scan": drive_scan,
        "storage_map": storage_map,
        "root_files": root_files,
        "note": (
            "Alguns tamanhos podem ser aproximados quando stopped_early=true. "
            "Pastas sensíveis como Windows, Program Files e ProgramData não devem ser apagadas manualmente."
        ),
    }


def _classify_path_for_cleanup(path: Path, size_gb: float) -> dict:
    path_text = str(path).lower()
    name = path.name.lower()

    if "\\windows" in path_text or "/windows" in path_text:
        return {
            "risk": "high",
            "category": "system",
            "suggestion": "Área do Windows. Não apagar manualmente. Use Limpeza de Disco ou Configurações do Windows.",
        }

    if "program files" in path_text:
        return {
            "risk": "high",
            "category": "installed_programs",
            "suggestion": "Programa instalado. Remova pelo desinstalador do Windows, não apagando a pasta diretamente.",
        }

    if "programdata" in path_text:
        return {
            "risk": "high",
            "category": "program_data",
            "suggestion": "Dados de programas. Revisar com muito cuidado.",
        }

    if "postgres" in path_text or "postgresql" in path_text:
        return {
            "risk": "high",
            "category": "database",
            "suggestion": "Pode conter dados do PostgreSQL. Não apagar manualmente sem backup e confirmação.",
        }

    if "appdata" in path_text:
        return {
            "risk": "medium",
            "category": "appdata",
            "suggestion": "Pode conter cache e dados de aplicativos. Investigar subpastas antes de limpar.",
        }

    if "$recycle.bin" in path_text:
        return {
            "risk": "low",
            "category": "recycle_bin",
            "suggestion": "Lixeira do Windows. Pode liberar espaço ao esvaziar, se você tiver certeza.",
        }

    if "temp" in path_text or "cache" in path_text:
        return {
            "risk": "medium",
            "category": "cache_or_temp",
            "suggestion": "Pode conter temporários/cache. Revisar antes de limpar.",
        }

    if name in ["downloads", "desktop", "videos", "vídeos", "pictures", "imagens", "documents", "documentos"]:
        return {
            "risk": "low",
            "category": "user_files",
            "suggestion": "Boa candidata para revisão manual, mover para outro disco ou apagar arquivos antigos.",
        }

    if size_gb >= 5:
        return {
            "risk": "medium",
            "category": "large_item",
            "suggestion": "Item grande. Investigar antes de qualquer ação.",
        }

    return {
        "risk": "low",
        "category": "general",
        "suggestion": "Sem alerta forte. Revisar apenas se necessário.",
    }


def scan_full_drive_exhaustive(
    root_path: str = "C:/",
    top_limit: int = 50,
) -> dict:
    """
    Varredura completa real do disco.

    Lê o máximo possível:
    - todos os arquivos acessíveis
    - todas as pastas acessíveis
    - não segue junctions/symlinks/reparse points
    - ignora o que não tiver permissão
    - não apaga nada

    Pode demorar vários minutos.
    """
    root = Path(root_path)

    if not root.exists():
        return {
            "mode": "full_exhaustive_scan",
            "error": f"Caminho não encontrado: {root_path}",
        }

    start_time = time.time()

    total_bytes = 0
    file_count = 0
    folder_count = 0
    skipped_count = 0
    permission_errors = []

    folder_sizes: dict[str, int] = {}

    largest_files_heap = []
    largest_folders_heap = []

    def add_to_heap(heap: list, item: tuple):
        heapq.heappush(heap, item)

        if len(heap) > top_limit:
            heapq.heappop(heap)

    def scan_folder(folder: Path) -> int:
        nonlocal file_count
        nonlocal folder_count
        nonlocal skipped_count
        nonlocal total_bytes

        folder_count += 1
        folder_total = 0

        try:
            children = list(folder.iterdir())
        except (OSError, PermissionError) as exc:
            skipped_count += 1

            if len(permission_errors) < 100:
                permission_errors.append(
                    {
                        "path": str(folder),
                        "error": str(exc),
                    }
                )

            return 0

        for child in children:
            try:
                if _is_reparse_point(child):
                    skipped_count += 1
                    continue

                if _safe_is_file(child):
                    size = child.stat().st_size
                    file_count += 1
                    folder_total += size
                    total_bytes += size

                    add_to_heap(
                        largest_files_heap,
                        (
                            size,
                            str(child),
                        ),
                    )

                elif _safe_is_dir(child):
                    child_total = scan_folder(child)
                    folder_total += child_total

            except (OSError, PermissionError) as exc:
                skipped_count += 1

                if len(permission_errors) < 100:
                    permission_errors.append(
                        {
                            "path": str(child),
                            "error": str(exc),
                        }
                    )

        folder_sizes[str(folder)] = folder_total

        add_to_heap(
            largest_folders_heap,
            (
                folder_total,
                str(folder),
            ),
        )

        return folder_total

    scan_folder(root)

    largest_files = []

    for size, path in sorted(largest_files_heap, reverse=True):
        size_gb = _bytes_to_gb(size)
        classification = _classify_path_for_cleanup(Path(path), size_gb)

        largest_files.append(
            {
                "path": path,
                "size_gb": size_gb,
                **classification,
            }
        )

    largest_folders = []

    for size, path in sorted(largest_folders_heap, reverse=True):
        size_gb = _bytes_to_gb(size)
        classification = _classify_path_for_cleanup(Path(path), size_gb)

        largest_folders.append(
            {
                "path": path,
                "size_gb": size_gb,
                **classification,
            }
        )

    safe_candidates = []
    risky_candidates = []

    for item in largest_folders + largest_files:
        if item.get("risk") == "high":
            risky_candidates.append(item)
        else:
            safe_candidates.append(item)

    elapsed_seconds = round(time.time() - start_time, 2)

    alerts = []
    recommendations = []

    if total_bytes > 0:
        alerts.append(
            f"Foram encontrados {_bytes_to_gb(total_bytes)} GB acessíveis durante a varredura."
        )

    for item in largest_folders[:15]:
        if item["risk"] == "high":
            recommendations.append(
                f"Não apagar manualmente {item['path']}. Motivo: {item['suggestion']}"
            )
        elif item["size_gb"] >= 1:
            recommendations.append(
                f"Investigar {item['path']}: ocupa {item['size_gb']} GB e pode ter potencial de limpeza/migração."
            )

    for item in largest_files[:15]:
        if item["risk"] == "high":
            recommendations.append(
                f"Não apagar manualmente {item['path']}. Motivo: {item['suggestion']}"
            )
        elif item["size_gb"] >= 1:
            recommendations.append(
                f"Arquivo grande para revisar: {item['path']} ocupa {item['size_gb']} GB."
            )

    recommendations = list(dict.fromkeys(recommendations))

    return {
        "mode": "full_exhaustive_scan",
        "message": "Varredura completa executada. Nenhum arquivo foi apagado.",
        "root": str(root),
        "elapsed_seconds": elapsed_seconds,
        "total_scanned_gb": _bytes_to_gb(total_bytes),
        "file_count": file_count,
        "folder_count": folder_count,
        "skipped_count": skipped_count,
        "permission_errors_sample": permission_errors,
        "largest_folders": largest_folders,
        "largest_files": largest_files,
        "safe_candidates": safe_candidates[:top_limit],
        "risky_candidates": risky_candidates[:top_limit],
        "alerts": alerts,
        "recommendations": recommendations,
        "note": (
            "Este scanner tentou ler tudo que estava acessível. "
            "Itens sem permissão, junctions, symlinks e reparse points foram ignorados por segurança."
        ),
    }

def scan_specific_folder_audit(
    folder_path: str,
    top_limit: int = 30,
) -> dict:
    """
    Audita uma pasta específica informada pelo usuário.

    Lê tudo que estiver dentro dela, quando acessível:
    - soma tamanho total
    - conta arquivos e pastas
    - lista maiores subpastas
    - lista maiores arquivos
    - classifica riscos
    - não apaga nada
    """
    root = Path(folder_path)

    if not root.exists():
        return {
            "mode": "specific_folder_audit",
            "found": False,
            "error": f"Pasta não encontrada: {folder_path}",
        }

    if not root.is_dir():
        return {
            "mode": "specific_folder_audit",
            "found": False,
            "error": f"O caminho informado não é uma pasta: {folder_path}",
        }

    start_time = time.time()

    total_bytes = 0
    file_count = 0
    folder_count = 0
    skipped_count = 0
    permission_errors = []

    largest_files_heap = []
    largest_folders_heap = []

    def add_to_heap(heap: list, item: tuple):
        heapq.heappush(heap, item)

        if len(heap) > top_limit:
            heapq.heappop(heap)

    def scan_folder(folder: Path) -> int:
        nonlocal total_bytes
        nonlocal file_count
        nonlocal folder_count
        nonlocal skipped_count

        folder_count += 1
        folder_total = 0

        try:
            children = list(folder.iterdir())
        except (OSError, PermissionError) as exc:
            skipped_count += 1

            if len(permission_errors) < 50:
                permission_errors.append(
                    {
                        "path": str(folder),
                        "error": str(exc),
                    }
                )

            return 0

        for child in children:
            try:
                if _is_reparse_point(child):
                    skipped_count += 1
                    continue

                if _safe_is_file(child):
                    size = child.stat().st_size
                    file_count += 1
                    folder_total += size
                    total_bytes += size

                    add_to_heap(
                        largest_files_heap,
                        (
                            size,
                            str(child),
                        ),
                    )

                elif _safe_is_dir(child):
                    child_total = scan_folder(child)
                    folder_total += child_total

            except (OSError, PermissionError) as exc:
                skipped_count += 1

                if len(permission_errors) < 50:
                    permission_errors.append(
                        {
                            "path": str(child),
                            "error": str(exc),
                        }
                    )

        add_to_heap(
            largest_folders_heap,
            (
                folder_total,
                str(folder),
            ),
        )

        return folder_total

    scan_folder(root)

    largest_files = []

    for size, path in sorted(largest_files_heap, reverse=True):
        size_gb = _bytes_to_gb(size)
        classification = _classify_path_for_cleanup(Path(path), size_gb)

        largest_files.append(
            {
                "path": path,
                "size_gb": size_gb,
                **classification,
            }
        )

    largest_folders = []

    for size, path in sorted(largest_folders_heap, reverse=True):
        size_gb = _bytes_to_gb(size)
        classification = _classify_path_for_cleanup(Path(path), size_gb)

        largest_folders.append(
            {
                "path": path,
                "size_gb": size_gb,
                **classification,
            }
        )

    total_gb = _bytes_to_gb(total_bytes)
    elapsed_seconds = round(time.time() - start_time, 2)

    safe_candidates = []
    risky_candidates = []

    for item in largest_folders + largest_files:
        if item.get("risk") == "high":
            risky_candidates.append(item)
        else:
            safe_candidates.append(item)

    alerts = []
    recommendations = []

    root_classification = _classify_path_for_cleanup(root, total_gb)

    if total_gb >= 10:
        alerts.append(f"A pasta analisada é grande: {total_gb} GB.")
    elif total_gb >= 3:
        alerts.append(f"A pasta analisada ocupa um espaço considerável: {total_gb} GB.")

    if root_classification.get("risk") == "high":
        recommendations.append(
            f"A pasta {root} é sensível. Não recomendo apagar manualmente."
        )

    for item in largest_folders[:10]:
        if item.get("risk") == "high":
            recommendations.append(
                f"Não apagar manualmente {item['path']}. Motivo: {item['suggestion']}"
            )
        elif item.get("size_gb", 0) >= 1:
            recommendations.append(
                f"Investigar {item['path']}: ocupa {item['size_gb']} GB."
            )

    for item in largest_files[:10]:
        if item.get("risk") == "high":
            recommendations.append(
                f"Não apagar manualmente {item['path']}. Motivo: {item['suggestion']}"
            )
        elif item.get("size_gb", 0) >= 0.5:
            recommendations.append(
                f"Arquivo grande para revisar: {item['path']} ocupa {item['size_gb']} GB."
            )

    recommendations = list(dict.fromkeys(recommendations))
    alerts = list(dict.fromkeys(alerts))

    if root_classification.get("risk") == "high":
        summary = (
            "A pasta analisada parece sensível. O Helix conseguiu mapear o conteúdo, "
            "mas qualquer limpeza deve ser feita por ferramenta oficial, desinstalador ou com muito cuidado."
        )
    elif total_gb >= 10:
        summary = (
            "A pasta analisada é grande e pode ter potencial de limpeza ou migração, "
            "mas os itens precisam ser revisados antes de qualquer ação."
        )
    else:
        summary = (
            "A pasta analisada não parece extremamente pesada, mas o relatório mostra os maiores itens internos."
        )

    return {
        "mode": "specific_folder_audit",
        "found": True,
        "message": "Auditoria de pasta específica executada. Nenhum arquivo foi apagado.",
        "path": str(root),
        "elapsed_seconds": elapsed_seconds,
        "total_size_gb": total_gb,
        "file_count": file_count,
        "folder_count": folder_count,
        "skipped_count": skipped_count,
        "root_risk": root_classification.get("risk"),
        "root_category": root_classification.get("category"),
        "summary": summary,
        "alerts": alerts,
        "recommendations": recommendations,
        "largest_folders": largest_folders,
        "largest_files": largest_files,
        "safe_candidates": safe_candidates[:top_limit],
        "risky_candidates": risky_candidates[:top_limit],
        "permission_errors_sample": permission_errors,
        "note": (
            "Este scanner analisou apenas a pasta informada pelo usuário. "
            "Itens sem permissão, junctions, symlinks e reparse points foram ignorados por segurança."
        ),
    }

def run_automatic_pc_checkup(
    drive_path: str = "C:/",
    low_free_space_gb: float = 30,
) -> dict:
    """
    Check-up automático leve/médio do PC.

    Faz:
    - métricas gerais
    - diagnóstico do sistema
    - análise de armazenamento
    - scanner médio se o disco estiver com pouco espaço

    Não apaga nada.
    """
    metrics = get_system_metrics()
    diagnostic = get_system_diagnostic()

    disk = metrics.get("disk", {})
    storage_devices = metrics.get("storage_devices", [])
    processes = metrics.get("processes", {})

    disk_percent = disk.get("percent", 0)
    disk_free_gb = disk.get("free_gb", 0)

    status = "good"
    alerts = []
    recommendations = []
    actions_taken = []
    next_steps = []

    storage_map = None
    storage_scan = None

    # Estado do disco principal
    if disk_free_gb <= low_free_space_gb or disk_percent >= 85:
        status = "warning"

        if disk_percent >= 90:
            status = "critical"

        alerts.append(
            f"O disco principal está com pouco espaço: {disk_free_gb} GB livres, {disk_percent}% usado."
        )

        recommendations.append(
            "Recomendo manter pelo menos 30 GB livres no C:, idealmente 50 GB para Windows, caches, updates e o Helix."
        )

        # Scanner médio automático
        storage_map = scan_storage_map(
            root_path=drive_path,
            max_depth=2,
            max_children_per_folder=30,
            max_files_per_folder=3000,
            min_size_gb=0.5,
        )

        storage_scan = scan_storage_usage()

        actions_taken.append(
            "Executei scanner médio de armazenamento porque o C: está com pouco espaço."
        )

    else:
        actions_taken.append(
            "Não executei scanner médio porque o espaço livre do disco principal está aceitável."
        )

    # RAM
    memory = metrics.get("memory", {})
    memory_percent = memory.get("percent", 0)

    if memory_percent >= 85:
        if status != "critical":
            status = "warning"

        alerts.append(
            f"Uso de RAM elevado: {memory_percent}% em uso."
        )

        recommendations.append(
            "Se o PC ficar pesado, revise navegador, Obsidian, Postgres, Discord e modelos locais como Ollama."
        )

    # CPU
    cpu = metrics.get("cpu", {})
    cpu_percent = cpu.get("percent", 0)

    if cpu_percent >= 85:
        if status != "critical":
            status = "warning"

        alerts.append(
            f"Uso de CPU elevado no momento: {cpu_percent}%."
        )

        recommendations.append(
            "Verifique se há algum processo pesado em execução antes de iniciar tarefas grandes."
        )

    # Processos importantes
    if processes.get("Ollama"):
        recommendations.append(
            "Ollama está rodando. Se não estiver usando IA local agora, fechar o Ollama pode liberar RAM."
        )

    if processes.get("Postgres"):
        recommendations.append(
            "Postgres está rodando. Isso é esperado para o Helix, mas ele consome recursos em segundo plano."
        )

    if processes.get("Obsidian"):
        actions_taken.append(
            "Obsidian está aberto. Bom para integração com o Helix Brain/Logs."
        )

    # Análise dos discos físicos
    for device in storage_devices:
        for volume in device.get("volumes", []):
            drive = volume.get("drive_letter")
            used_percent = volume.get("used_percent", 0)
            free_gb = volume.get("free_gb", 0)

            if used_percent >= 90:
                status = "critical"
                alerts.append(
                    f"Unidade {drive} está crítica: {used_percent}% usado, {free_gb} GB livres."
                )

            elif used_percent >= 80:
                if status != "critical":
                    status = "warning"

                alerts.append(
                    f"Unidade {drive} está com uso alto: {used_percent}% usado, {free_gb} GB livres."
                )

    # Avaliar mapa de armazenamento se tiver rodado
    storage_findings = []

    if storage_map:
        largest_folders = storage_map.get("largest_folders", [])

        for folder in largest_folders[:10]:
            storage_findings.append(
                {
                    "path": folder.get("path"),
                    "size_gb": folder.get("size_gb"),
                    "risk": folder.get("risk"),
                    "category": folder.get("category"),
                    "suggestion": folder.get("suggestion"),
                    "stopped_early": folder.get("stopped_early"),
                }
            )

        for folder in largest_folders[:5]:
            path = folder.get("path")
            size_gb = folder.get("size_gb", 0)
            risk = folder.get("risk")

            if risk == "high":
                recommendations.append(
                    f"Não apagar manualmente {path}. Use ferramenta oficial, desinstalador ou análise guiada."
                )
            elif size_gb >= 1:
                recommendations.append(
                    f"Investigar {path}: ocupa aproximadamente {size_gb} GB e pode ter potencial de limpeza."
                )

    # Próximos passos inteligentes
    if disk_free_gb <= low_free_space_gb:
        next_steps.append(
            "Investigar as maiores pastas apontadas pelo scanner médio."
        )
        next_steps.append(
            "Rodar auditoria específica em uma pasta suspeita, por exemplo: analise a pasta C:\\Users\\Marcos\\AppData\\Local"
        )
        next_steps.append(
            "Rodar auditoria completa pesada apenas quando necessário, pois pode demorar vários minutos."
        )

    if not alerts:
        summary = "O PC parece saudável no momento. Nenhum alerta importante encontrado."
    elif status == "critical":
        summary = "O PC tem pontos críticos que merecem atenção, principalmente armazenamento."
    else:
        summary = "O PC está funcional, mas há pontos de atenção."

    recommendations = list(dict.fromkeys(recommendations))
    alerts = list(dict.fromkeys(alerts))
    actions_taken = list(dict.fromkeys(actions_taken))
    next_steps = list(dict.fromkeys(next_steps))

    return {
        "mode": "automatic_pc_checkup",
        "message": "Check-up automático executado. Nenhum arquivo foi apagado.",
        "status": status,
        "summary": summary,
        "alerts": alerts,
        "recommendations": recommendations,
        "actions_taken": actions_taken,
        "next_steps": next_steps,
        "storage_findings": storage_findings,
        "metrics": metrics,
        "diagnostic": diagnostic,
        "storage_map": storage_map,
        "storage_scan": storage_scan,
        "note": (
            "Este check-up é leve/médio. Ele só executa scanner de armazenamento "
            "quando detecta pouco espaço no disco principal."
        ),
    }