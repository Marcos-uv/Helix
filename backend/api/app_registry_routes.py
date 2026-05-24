from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.services.app_registry_service import (
    cleanup_known_apps,
    deactivate_known_app,
    find_known_app,
    list_known_apps,
    refresh_known_apps_cache,
)
from backend.services.app_scanner_service import scan_apps


router = APIRouter(prefix="/apps", tags=["Apps"])


@router.get("/known")
def get_known_apps(
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    apps = list_known_apps(db, limit=limit)

    return {
        "count": len(apps),
        "apps": apps,
    }


@router.get("/find")
def find_app(
    name: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
):
    app = find_known_app(db, name)

    if not app:
        return {
            "found": False,
            "query": name,
            "app": None,
        }

    return {
        "found": True,
        "query": name,
        "app": app,
    }


@router.post("/scan")
def scan_installed_apps(
    max_depth: int = Query(default=5, ge=1, le=10),
    limit: int = Query(default=300, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    return scan_apps(db, max_depth=max_depth, limit=limit)

@router.post("/cleanup")
def cleanup_apps(
    db: Session = Depends(get_db),
):
    return cleanup_known_apps(db)


@router.post("/cache/refresh")
def refresh_apps_cache(
    db: Session = Depends(get_db),
):
    return refresh_known_apps_cache(db)


@router.delete("/{app_id}")
def delete_known_app(
    app_id: int,
    db: Session = Depends(get_db),
):
    return deactivate_known_app(db, app_id)