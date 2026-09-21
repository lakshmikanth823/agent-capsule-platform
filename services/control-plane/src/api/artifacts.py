"""
Artifact upload endpoints.
"""
import hashlib
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from auth.dependencies import get_current_user
from auth.models import AuthenticatedUser
from storage import get_storage_driver

router = APIRouter(tags=["Artifacts"])


@router.post("/artifacts")
async def upload_artifact(
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Upload an application bundle to the object storage abstraction.
    Returns storage reference and SHA256 hash.
    """
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "EMPTY_ARTIFACT", "message": "Uploaded artifact bundle cannot be empty."},
        )

    sha256_hash = hashlib.sha256(content).hexdigest()
    storage_path = f"artifacts/{sha256_hash[:2]}/{sha256_hash}.tar.gz"

    storage = get_storage_driver()
    ref = await storage.put(storage_path, content, content_type="application/gzip")

    return {
        "ref": ref,
        "sha256": sha256_hash,
        "size_bytes": len(content),
    }
