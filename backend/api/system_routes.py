from fastapi import APIRouter

from backend.core.system_monitor import (
    get_system_metrics,
    get_system_diagnostic,
    get_hardware_info,
    scan_storage_usage,
    scan_drive_top_level,
    scan_storage_map,
    scan_full_drive_exhaustive,
    scan_specific_folder_audit,
    run_automatic_pc_checkup,
)


router = APIRouter()


@router.get("/system")
def system_metrics():
    return get_system_metrics()


@router.get("/system/diagnostic")
def system_diagnostic():
    return get_system_diagnostic()


@router.get("/system/hardware")
def system_hardware():
    return get_hardware_info()


@router.get("/system/storage-scan")
def system_storage_scan():
    return scan_storage_usage()


@router.get("/system/drive-scan")
def system_drive_scan(drive: str = "C:/"):
    return scan_drive_top_level(drive_path=drive)


@router.get("/system/storage-map")
def system_storage_map(
    root: str = "C:/",
    max_depth: int = 2,
    min_size_gb: float = 0.5,
):
    return scan_storage_map(
        root_path=root,
        max_depth=max_depth,
        min_size_gb=min_size_gb,
    )


@router.get("/system/storage-audit/full")
def system_storage_audit_full(
    root: str = "C:/",
    top_limit: int = 50,
):
    return scan_full_drive_exhaustive(
        root_path=root,
        top_limit=top_limit,
    )


@router.get("/system/folder-audit")
def system_folder_audit(
    path: str,
    top_limit: int = 30,
):
    return scan_specific_folder_audit(
        folder_path=path,
        top_limit=top_limit,
    )


@router.get("/system/checkup")
def system_checkup(
    drive: str = "C:/",
    low_free_space_gb: float = 30,
):
    return run_automatic_pc_checkup(
        drive_path=drive,
        low_free_space_gb=low_free_space_gb,
    )