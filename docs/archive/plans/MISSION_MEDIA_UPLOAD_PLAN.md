# Mission Media Upload Feature - Planning Document

## Executive Summary

This document outlines the planning for adding image and short video upload functionality for deployment and recovery operations, linking media to mission overviews. The feature would allow pilots and admins to upload photos and videos that would be displayed in the mission overview section of the platform.

**Updated assumption:** For initial production, media will be stored on the local host filesystem (production server). The plan below includes hardening steps and operational controls for local storage, plus a migration-ready path to cloud storage later.

## Current Application Assessment

### ✅ **Conducive Aspects**

1. **Existing File Upload Infrastructure**
   - The application already has file upload functionality for:
     - Mission plan documents (`/api/missions/{mission_id}/overview/upload_plan`)
     - Knowledge base documents (`/api/knowledge/documents/upload`)
   - Uses FastAPI's `UploadFile` and `File` dependencies
   - File storage pattern: `web/static/{category}/{files}`

2. **Static File Serving**
   - Static files mounted at `/static` via FastAPI's `StaticFiles`
   - Directory structure: `web/static/` with subdirectories for different content types
   - Existing directories: `mission_plans/`, `mission_reports/`, `knowledge_base/documents/`

3. **Authentication & Authorization**
   - Role-based access control already implemented (`UserRoleEnum.admin`, `UserRoleEnum.pilot`)
   - Dependency injection for `get_current_active_user`, `get_current_admin_user`
   - Can easily add `get_current_pilot_user` for pilot-specific endpoints

4. **Mission Overview Structure**
   - `MissionOverview` model already exists with fields for URLs (`document_url`, `weekly_report_url`, etc.)
   - Mission overview editing UI exists at `/admin/mission_overviews.html`
   - Mission info API endpoint: `/api/missions/{mission_id}/info`

5. **Database Architecture**
   - SQLModel/SQLAlchemy ORM with SQLite backend
   - Alembic migrations already in place
   - Relationship patterns established (e.g., `MissionGoal`, `MissionNote` linked to missions)

### ⚠️ **Considerations & Limitations**

1. **File Storage**
   - Currently using local filesystem storage (`web/static/`)
   - No cloud storage integration (S3, Azure Blob, etc.)
   - No CDN for media delivery
   - Storage location is relative to project root

2. **File Size Limits**
   - Knowledge base has configurable max size (`knowledge_base_max_upload_size_mb: 50`)
   - No existing video upload handling
   - Videos can be large; need size limits and processing considerations

3. **Media Processing**
   - No image resizing/optimization currently
   - No video transcoding/compression
   - No thumbnail generation

4. **Database Schema**
   - `MissionOverview` model uses single URL fields
   - Would need new table for multiple media items per mission
   - Current structure doesn't support multiple files per mission

## Proposed Feature Design

### 1. Database Schema

#### New Table: `MissionMedia`

```python
class MissionMedia(SQLModel, table=True):
    """Mission media (photos/videos) database table."""
    __tablename__ = "mission_media"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    mission_id: str = SQLModelField(index=True, description="Mission identifier")
    media_type: str = SQLModelField(description="'photo' or 'video'")
    file_path: str = SQLModelField(description="Relative path to file in static directory")
    file_name: str = SQLModelField(description="Original filename")
    file_size: int = SQLModelField(description="File size in bytes")
    mime_type: str = SQLModelField(description="MIME type (e.g., 'image/jpeg', 'video/mp4')")
    
    # Metadata
    caption: Optional[str] = SQLModelField(default=None, sa_column=Column(Text))
    operation_type: Optional[str] = SQLModelField(default=None, description="'deployment' or 'recovery'")
    uploaded_by_username: str = SQLModelField(index=True)
    uploaded_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    
    # For videos: thumbnail path
    thumbnail_path: Optional[str] = SQLModelField(default=None)
    
    # Ordering/display
    display_order: int = SQLModelField(default=0, description="Order for display in gallery")
    is_featured: bool = SQLModelField(default=False, description="Featured image for mission overview")
```

**Migration Considerations:**
- Add new table via Alembic migration
- Index on `mission_id` for fast lookups
- Index on `uploaded_by_username` for user activity tracking

### 2. File Storage Structure

```
web/static/
  mission_media/
    {mission_id}/
      photos/
        {media_id}_{timestamp}.{ext}
      videos/
        {media_id}_{timestamp}.{ext}
      thumbnails/
        {media_id}_thumb.{ext}
```

**Rationale:**
- Organized by mission ID for easy cleanup/deletion
- Separate folders for photos/videos for organization
- Thumbnails stored separately for videos
- Timestamped filenames prevent collisions

**Local storage hardening (production server):**
- Store media outside the code directory if possible (e.g., `/var/lib/wgbs/media`) and bind-mount or symlink into `web/static/mission_media` to keep deploys clean.
- Enforce restrictive filesystem permissions on the media root (`read/execute` for the web user, `write` only for the app user).
- Add a dedicated config setting for `mission_media_root_path` so the storage location is not hard-coded.

### 3. API Endpoints

#### Upload Media
```
POST /api/missions/{mission_id}/media/upload
- Requires: active user (pilot or admin)
- Accepts: multipart/form-data
  - file: UploadFile (required)
  - caption: str (optional)
  - operation_type: str (optional, 'deployment' or 'recovery')
- Returns: MissionMedia object with file_url
```

#### List Mission Media
```
GET /api/missions/{mission_id}/media
- Requires: active user
- Query params:
  - media_type: Optional[str] ('photo' or 'video')
  - operation_type: Optional[str] ('deployment' or 'recovery')
- Returns: List[MissionMedia]
```

#### Get Single Media Item
```
GET /api/missions/{mission_id}/media/{media_id}
- Requires: active user
- Returns: MissionMedia
```

#### Update Media Metadata
```
PUT /api/missions/{mission_id}/media/{media_id}
- Requires: active user (pilot can only update own uploads, admin can update any)
- Body: MissionMediaUpdate (caption, operation_type, display_order, is_featured)
- Returns: MissionMedia
```

#### Delete Media
```
DELETE /api/missions/{mission_id}/media/{media_id}
- Requires: active user (pilot can only delete own uploads, admin can delete any)
- Returns: 204 No Content
```

### 4. Frontend UI/UX

#### Admin Mission Overviews Page (`/admin/mission_overviews.html`)

**New Section: "Deployment & Recovery Media"**

```html
<div class="mb-3">
    <label class="form-label">Deployment & Recovery Media</label>
    <div class="alert alert-info mb-2" style="font-size: 0.9em;">
        <i class="fas fa-info-circle"></i> Upload photos and short videos from deployment and recovery operations.
    </div>
    
    <!-- Upload Interface -->
    <div class="card mb-3">
        <div class="card-body">
            <form id="mediaUploadForm" enctype="multipart/form-data">
                <div class="mb-3">
                    <label for="mediaFileInput" class="form-label">Select File:</label>
                    <input type="file" class="form-control" id="mediaFileInput" 
                           accept="image/*,video/*" multiple>
                    <div class="form-text">Accepted: JPG, PNG, GIF, MP4, MOV (max 50MB per file)</div>
                </div>
                <div class="mb-3">
                    <label for="operationTypeSelect" class="form-label">Operation Type:</label>
                    <select class="form-select" id="operationTypeSelect">
                        <option value="">Not specified</option>
                        <option value="deployment">Deployment</option>
                        <option value="recovery">Recovery</option>
                    </select>
                </div>
                <div class="mb-3">
                    <label for="mediaCaption" class="form-label">Caption (optional):</label>
                    <textarea class="form-control" id="mediaCaption" rows="2" 
                              placeholder="Add a caption describing this photo/video..."></textarea>
                </div>
                <button type="submit" class="btn btn-primary">
                    <i class="fas fa-upload"></i> Upload Media
                </button>
            </form>
        </div>
    </div>
    
    <!-- Media Gallery -->
    <div id="mediaGallery" class="row g-3">
        <!-- Media items will be dynamically loaded here -->
    </div>
</div>
```

**Media Gallery Display:**
- Grid layout with thumbnails
- Hover overlay showing caption and operation type
- Click to view full-size (lightbox/modal)
- Videos: play button overlay, thumbnail preview
- Admin controls: edit caption, delete, set as featured
- Filter by operation type (deployment/recovery)
- Sort by upload date (newest first)

#### Mission Overview Display (`home.html`)

**New Section in Mission Overview Card:**

```html
{% if mission_info.media and mission_info.media|length > 0 %}
<div class="mission-media-section mt-3">
    <h5 class="mb-2">Deployment & Recovery Media</h5>
    <div class="row g-2">
        {% for media in mission_info.media[:6] %}
        <div class="col-4 col-md-3">
            <a href="{{ media.file_url }}" data-lightbox="mission-media" 
               data-title="{{ media.caption or 'Mission Media' }}">
                {% if media.media_type == 'photo' %}
                    <img src="{{ media.file_url }}" class="img-fluid rounded" 
                         alt="{{ media.caption or 'Mission photo' }}" 
                         style="object-fit: cover; height: 100px; width: 100%;">
                {% else %}
                    <div class="position-relative">
                        <img src="{{ media.thumbnail_path or media.file_url }}" 
                             class="img-fluid rounded" 
                             style="object-fit: cover; height: 100px; width: 100%;">
                        <div class="position-absolute top-50 start-50 translate-middle">
                            <i class="fas fa-play-circle text-white" style="font-size: 2rem;"></i>
                        </div>
                    </div>
                {% endif %}
            </a>
        </div>
        {% endfor %}
    </div>
    {% if mission_info.media|length > 6 %}
    <div class="mt-2">
        <a href="/mission/{{ mission_id }}/media" class="btn btn-sm btn-outline-primary">
            View All Media ({{ mission_info.media|length }})
        </a>
    </div>
    {% endif %}
</div>
{% endif %}
```

### 5. File Validation & Processing

#### Image Handling
- **Accepted formats:** JPEG, PNG, GIF, WebP
- **Max size:** 10MB per image
- **Processing:**
  - Generate thumbnail (200x200px) for gallery display
  - Optional: Resize large images to max 1920px width (maintain aspect ratio)
  - Store original + thumbnail

#### Video Handling
- **Accepted formats:** MP4, MOV, AVI
- **Max size:** 50MB per video
- **Max duration:** 2 minutes (configurable)
- **Processing:**
  - Extract thumbnail frame (first frame or middle frame)
  - Optional: Transcode to MP4/H.264 for web compatibility
  - Store original + thumbnail

#### Validation Logic
```python
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp"
}

ALLOWED_VIDEO_TYPES = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/x-msvideo": "avi"
}

MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_VIDEO_SIZE = 50 * 1024 * 1024  # 50MB
MAX_VIDEO_DURATION_SECONDS = 120  # 2 minutes
```

### 6. Security Considerations

1. **File Type Validation**
   - Validate MIME type, not just file extension
   - Check file magic bytes/headers
   - Reject executable files, scripts, etc.

2. **File Size Limits**
   - Enforce limits at upload endpoint
   - Consider total storage per mission

3. **Access Control**
   - Only active users (pilots/admins) can upload
   - Pilots can only delete their own uploads
   - Admins can delete any upload
   - All active users can view media

4. **File Naming**
   - Sanitize filenames (remove special characters, path traversal)
   - Use UUID or timestamp-based naming
   - Store original filename in database

5. **Storage Security**
   - Files served through static file handler (FastAPI StaticFiles)
   - Consider adding authentication middleware for sensitive media
   - Or serve through authenticated API endpoints

6. **Quota and Abuse Controls**
   - Per-user rate limiting on upload endpoints
   - Per-mission storage quota (soft warning + hard cap)
   - Restrict max number of files per upload to prevent abuse

7. **Content Scanning (Optional)**
   - Virus/malware scanning for uploads (ClamAV or similar)
   - Flag suspicious file types or mismatched MIME headers

8. **Authenticated Media Serving (Recommended)**
   - For sensitive deployments, prefer `GET /api/missions/{id}/media/{media_id}/file` with auth checks
   - Use signed, time-limited URLs if/when cloud storage is added

### 7. Configuration Settings

Add to `app/config.py`:

```python
# Mission Media Settings
mission_media_root_path: str = "web/static/mission_media"
mission_media_max_image_size_mb: int = 10
mission_media_max_video_size_mb: int = 50
mission_media_max_video_duration_seconds: int = 120
mission_media_generate_thumbnails: bool = True
mission_media_resize_images: bool = True
mission_media_max_image_width: int = 1920
mission_media_max_files_per_upload: int = 10
mission_media_total_quota_mb_per_mission: int = 1024
```

### 8. Dependencies

**New Python Packages Required:**

```txt
# Image processing
Pillow>=10.0.0  # For image resizing, thumbnail generation

# Video processing (optional, for advanced features)
opencv-python>=4.8.0  # For video thumbnail extraction
# OR
ffmpeg-python>=0.2.0  # Alternative for video processing
```

**Note:** Video processing is optional. Can start with basic video upload and add processing later.

### 9. Frontend Dependencies

**JavaScript Libraries:**
- Lightbox library for image/video viewing (e.g., `lightbox2`, `GLightbox`)
- Or use Bootstrap modals for custom implementation

## Implementation Phases

### Phase 1: Basic Photo Upload (MVP)
1. Database migration for `MissionMedia` table
2. Backend API endpoints (upload, list, delete)
3. Basic file storage (no processing)
4. Admin UI for upload and gallery
5. Display in mission overview

**Timeline:** ~1-2 weeks

### Phase 2: Enhanced Features
1. Image thumbnail generation
2. Video upload support
3. Video thumbnail extraction
4. Operation type filtering
5. Caption editing
6. Featured image selection

**Timeline:** ~1 week

### Phase 3: Optimization & Polish
1. Image resizing/optimization
2. Video transcoding (if needed)
3. Lightbox/gallery viewer
4. Bulk upload support
5. Drag-and-drop upload
6. Progress indicators

**Timeline:** ~1 week

## Implications & Considerations

### Storage Implications

1. **Disk Space**
   - Photos: ~2-5MB each (with thumbnails)
   - Videos: ~10-50MB each
   - Estimate: 100 photos + 20 videos per mission = ~500MB-1GB per mission
   - **Action:** Monitor storage usage, implement cleanup policies

2. **Backup Strategy**
   - Media files should be included in backups
   - Consider separate backup for media vs. database
   - **Action:** Update backup procedures

3. **Storage Location**
   - Current: Local filesystem (`web/static/`)
   - **Future consideration:** Cloud storage (S3, Azure Blob) for scalability
   - **Action:** Design file paths to be easily migrated to cloud storage

4. **Local Storage Operations**
   - **Action:** Add disk monitoring and alerts (low disk, high usage)
   - **Action:** Document a cleanup/archival policy for older missions
   - **Action:** Ensure daily backups include both DB + media root

### Performance Implications

1. **Page Load Times**
   - Mission overview pages may load slower with many media items
   - **Solution:** Lazy loading, pagination, thumbnail-only initial load

2. **Upload Performance**
   - Large files may timeout
   - **Solution:** Chunked uploads, progress indicators, async processing

3. **Database Queries**
   - Additional queries for media items
   - **Solution:** Efficient indexing, consider caching

### User Experience Implications

1. **Mobile Upload**
   - Users may upload from mobile devices in field
   - **Consideration:** Ensure mobile-friendly upload UI
   - **Consideration:** Handle large mobile photos/videos

2. **Network Conditions**
   - Field operations may have poor connectivity
   - **Consideration:** Offline upload queue, retry logic

3. **Organization**
   - Many media items per mission could be overwhelming
   - **Solution:** Filtering, sorting, search by caption

### Maintenance Implications

1. **File Cleanup**
   - Need process to remove media when missions are archived
   - **Action:** Implement cleanup job or manual process

2. **Orphaned Files**
   - Files may exist without database records (or vice versa)
   - **Action:** Periodic integrity check script

3. **Migration**
   - If moving to cloud storage, need migration path
   - **Action:** Design file paths to be storage-agnostic

### Security Implications

1. **Malicious Files**
   - Risk of uploaded malware, scripts
   - **Solution:** Strict file type validation, virus scanning (optional)

2. **Sensitive Information**
   - Photos/videos may contain sensitive operational details
   - **Solution:** Access control, consider watermarking

3. **Data Privacy**
   - May contain personnel, equipment, location data
   - **Solution:** Review privacy policies, user consent

4. **Local Storage Exposure**
   - Static hosting can leak files if URLs are guessed
   - **Solution:** Authenticated file endpoints or obfuscated paths/UUIDs
   - **Solution:** Avoid storing under a publicly browsable directory tree

## Is Current Setup Conducive?

### ✅ **YES - Highly Conducive**

**Reasons:**
1. **Existing Patterns:** File upload infrastructure already exists and can be replicated
2. **Database Architecture:** SQLModel/SQLAlchemy makes adding new tables straightforward
3. **Authentication:** Role-based access control is already implemented
4. **Frontend Structure:** Mission overview UI exists and can be extended
5. **Static File Serving:** FastAPI StaticFiles is already configured
6. **Migration System:** Alembic is in place for schema changes

### ⚠️ **Minor Adjustments Needed**

1. **File Size Limits:** Need to configure appropriate limits for media
2. **Media Processing:** Need to add image/video processing libraries
3. **UI Components:** Need to add gallery/lightbox components
4. **Storage Monitoring:** Need to track storage usage

### 📋 **Recommended Approach**

1. **Start Simple:** Begin with basic photo upload (Phase 1)
2. **Iterate:** Add video support and enhancements (Phase 2)
3. **Optimize:** Add processing and polish (Phase 3)
4. **Monitor:** Track storage usage and performance
5. **Plan Migration:** Design for potential cloud storage migration

## Conclusion

The current application architecture is **well-suited** for adding mission media upload functionality. The existing file upload patterns, authentication system, and database structure provide a solid foundation. The main considerations are storage management, file processing, and user experience enhancements, all of which are manageable within the current architecture.

The feature would integrate seamlessly with the existing mission overview system and provide valuable visual documentation for deployment and recovery operations.

## Cloud Storage Options (Future Migration)

If/when you move off local storage, the following options fit this architecture well:
- **AWS S3** + CloudFront: most standard, strong lifecycle rules and IAM controls.
- **Azure Blob Storage** + CDN: good if you are already on Microsoft stack.
- **Google Cloud Storage** + Cloud CDN: similar to S3 with strong region support.
- **Cloudflare R2**: no egress fees, easy S3-compatible API.
- **Backblaze B2**: cost-effective for large archives.
- **Self-hosted S3-compatible (MinIO)**: good interim step if you want private, on-prem storage.

**Recommendation for migration readiness:** keep `file_path` relative and store a `storage_provider` enum (e.g., `local`, `s3`, `azure`) so moving storage later is a config change, not a schema overhaul.



