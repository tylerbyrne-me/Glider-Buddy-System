# Static Map Plotting Feature - Implementation Plan

## Feature Overview
Add static map plot generation capabilities to complement the existing interactive map and KML export features. This will allow users to generate publication-ready map visualizations of mission telemetry tracks using matplotlib/cartopy.

## Use Cases
1. **Publications/Reports**: High-resolution static images for documents, presentations
2. **Email Attachments**: Share mission progress without requiring KML software
3. **Archive/Print**: Physical copies of mission tracks
4. **Multi-format Support**: PNG (standard), SVG (scalable), PDF (document-ready)

## Current System Analysis

### Existing Infrastructure
- ✅ **Cartopy**: Already installed and used in `app/core/plotting.py`
- ✅ **Matplotlib**: Used extensively for sensor trend plots and PDF reports
- ✅ **Telemetry Processing**: Standardized data pipeline in `app/core/processors.py`
- ✅ **Map Utilities**: Track point preparation in `app/core/map_utils.py`
- ✅ **Base64 Image Pattern**: Error analysis router demonstrates endpoint pattern (`/plot/*`)

### Existing Map Plotting
- `plot_telemetry_for_report()` in `app/core/plotting.py` (lines 294-324)
  - Uses Cartopy with PlateCarree projection
  - Speed-colored scatter plot
  - Start/end markers
  - PDF-optimized (8.27x11.69 inches)
  - Coastlines, land, borders, gridlines

## Feature Design

### 1. New Plotting Functions

#### Location: `app/core/plotting.py` (extend existing module)

**Function 1: `generate_static_map_plot()`**
- **Purpose**: Generate a standalone static map image from telemetry data
- **Parameters**:
  - `df: pd.DataFrame` - Preprocessed telemetry DataFrame (standardized columns)
  - `mission_id: str` - Mission identifier
  - `plot_style: str` - Style preset: "simple", "detailed", "publication"
  - `color_by: Optional[str]` - Color scheme: None (solid), "speed", "time", "heading"
  - `show_start_end: bool = True` - Show start/end markers
  - `include_bathymetry: bool = False` - Add depth contours (future)
  - `figure_size: Tuple[float, float]` - Width, height in inches
  - `dpi: int = 150` - Output resolution
  - `format: str = "png"` - Output format: "png", "svg", "pdf"
- **Returns**: `io.BytesIO` buffer containing image data
- **Features**:
  - Automatic extent calculation with padding
  - Configurable basemap features (coastlines, land, borders)
  - Gridlines with lat/lon labels
  - Legend (if color_by is set)
  - Title with mission ID and time range
  - Scale bar option (future)

**Function 2: `generate_multi_mission_map()`**
- **Purpose**: Plot multiple mission tracks on one map
- **Parameters**:
  - `mission_tracks: List[Tuple[str, pd.DataFrame]]` - List of (mission_id, df) tuples
  - `color_palette: Optional[List[str]]` - Custom colors, or use default
  - Other parameters similar to single mission plot
- **Returns**: `io.BytesIO` buffer
- **Features**:
  - Different color per mission
  - Mission legend
  - Combined extent for all missions

### 2. API Endpoints

#### Location: `app/routers/map_router.py` (extend existing router)

**Endpoint 1: `GET /api/map/plot/{mission_id}`**
- **Purpose**: Generate static map plot for single mission
- **Query Parameters**:
  - `hours_back: int = 72` - Time range
  - `start_date: Optional[datetime]` - Start date (alternative to hours_back)
  - `end_date: Optional[datetime]` - End date
  - `plot_style: str = "detailed"` - Style preset
  - `color_by: Optional[str] = None` - Color scheme (None, "speed", "time")
  - `show_start_end: bool = True` - Show markers
  - `format: str = "png"` - Output format (png, svg, pdf)
  - `dpi: int = 150` - Resolution
  - `width: float = 10` - Image width (inches)
  - `height: float = 8` - Image height (inches)
- **Returns**: StreamingResponse with appropriate content-type
  - `image/png` for PNG
  - `image/svg+xml` for SVG
  - `application/pdf` for PDF
- **Headers**: Content-Disposition with filename

**Endpoint 2: `GET /api/map/plot/multiple`**
- **Purpose**: Generate multi-mission static map
- **Query Parameters**:
  - `mission_ids: str` - Comma-separated mission IDs (required)
  - `hours_back: int = 72` - Time range (applied to all missions)
  - `plot_style: str = "detailed"`
  - `format: str = "png"`
  - `dpi: int = 150`
  - Other parameters similar to single mission
- **Returns**: StreamingResponse with map image
- **Features**:
  - Automatic color assignment per mission
  - Combined legend

**Endpoint 3: `GET /api/map/plot/preview/{mission_id}`**
- **Purpose**: Return base64-encoded preview (smaller, faster for UI thumbnails)
- **Query Parameters**: Same as main plot endpoint, but:
  - `dpi: int = 72` (lower resolution)
  - `width: float = 5` (smaller size)
- **Returns**: JSON with `{"image": "data:image/png;base64,..."}`
- **Use Case**: Show preview in map generator panel before download

### 3. Plot Style Presets

**Style: "simple"**
- Minimal features: track line only
- No gridlines, minimal basemap
- Fast rendering
- Use case: Quick previews, low-resolution needs

**Style: "detailed"** (default)
- Full basemap: coastlines, land, borders
- Gridlines with labels
- Start/end markers
- Legend (if applicable)
- Use case: Standard reports, presentations

**Style: "publication"**
- High-resolution (300 DPI default)
- Enhanced typography (larger fonts, better spacing)
- No watermark (clean for publications)
- Professional styling
- Use case: Scientific publications, official reports

### 4. Color Schemes

**Solid Color** (`color_by=None`)
- Single color for entire track
- Default: Mission-specific colors from existing palette
- Parameter: `track_color: str = "#3388ff"`

**Speed Over Ground** (`color_by="speed"`)
- Color gradient based on SpeedOverGround column
- Colormap: 'plasma' (perceptually uniform, colorblind-friendly)
- Colorbar legend
- Speed range from data min/max or configurable

**Time-based** (`color_by="time"`)
- Gradient from start (dark) to end (bright)
- Shows temporal progression
- Colormap: 'viridis' or sequential blue

**Heading-based** (`color_by="heading"`)
- Color by GliderHeading (future)
- Circular colormap (hue-based)
- Use case: Analyzing navigation patterns

### 5. Frontend Integration

#### Location: `web/static/js/map_generator.js` (extend existing)

**New UI Elements**:
- **"Generate Static Plot" button** in map generator panel
- **Format selector**: PNG / SVG / PDF dropdown
- **Style selector**: Simple / Detailed / Publication
- **Color scheme selector**: Solid / Speed / Time
- **Preview pane**: Show thumbnail before download (optional)

**JavaScript Function**:
```javascript
async function generateStaticPlot() {
    const missionId = document.getElementById('mapMissionSelect').value;
    const hoursBack = parseInt(document.getElementById('mapHoursBack').value);
    const format = document.getElementById('plotFormatSelect').value;
    const style = document.getElementById('plotStyleSelect').value;
    const colorBy = document.getElementById('plotColorSelect').value;
    
    // Build query string
    const params = new URLSearchParams({
        hours_back: hoursBack,
        format: format,
        plot_style: style,
        color_by: colorBy || undefined,
        show_start_end: true
    });
    
    // Download file
    window.location.href = `/api/map/plot/${missionId}?${params.toString()}`;
}
```

### 6. Implementation Details

#### Matplotlib Figure Management
- Use context manager or explicit cleanup (`plt.close()`)
- Avoid memory leaks with long-running server
- Reuse figure objects when possible for multi-mission plots

#### Coordinate System
- Use Cartopy's `PlateCarree` projection (same as existing report plots)
- Ensure extent calculation handles edge cases:
  - Single point tracks
  - Tracks crossing date line (unlikely for Atlantic missions)
  - Very narrow/long tracks

#### Performance Considerations
- Downsampling for very large datasets (reuse `prepare_track_points` logic)
- Lazy loading: Only generate when requested
- Cache generated plots? (Probably not - too large, user-specific)

#### Error Handling
- Handle empty DataFrames gracefully
- Invalid date ranges
- Missing columns (fallback to basic plot)
- File I/O errors (BytesIO in memory should avoid most)

### 7. Dependencies
- ✅ Already available:
  - `matplotlib`
  - `cartopy`
  - `pandas`
  - `numpy`
- No new dependencies required

### 8. File Structure

```
app/
├── core/
│   └── plotting.py          # Extend with static map functions
├── routers/
│   └── map_router.py        # Add plot endpoints
web/
└── static/
    └── js/
        └── map_generator.js # Add static plot UI
```

### 9. Future Enhancements (Phase 2+)

1. **Bathymetry Overlay**: Add depth contours from datasets
2. **Waypoint Markers**: Show mission waypoints on track
3. **Sensor Overlays**: Optional heatmaps for sensor data (CTD, weather)
4. **Animation Frames**: Generate series of plots for time-lapse animations
5. **Custom Basemaps**: Satellite imagery, different map styles
6. **Track Statistics Overlay**: Text box with distance, avg speed, etc.
7. **Scale Bar**: Map-scale indicator
8. **North Arrow**: Compass rose
9. **Temporal Subsetting**: Highlight specific time ranges

### 10. Implementation Phases

**Phase 1: Basic Static Plotting** (Initial Implementation)
- ✅ Single mission static plot
- ✅ Three style presets (simple, detailed, publication)
- ✅ Solid color and speed-based coloring
- ✅ PNG, SVG, PDF formats
- ✅ API endpoints integrated into map router
- ✅ Frontend button in map generator panel

**Phase 2: Multi-Mission & Enhanced Styling**
- Multiple missions on one plot
- Time-based coloring
- Preview endpoint (base64 thumbnail)
- Enhanced legend formatting

**Phase 3: Advanced Features**
- Bathymetry overlay
- Waypoint markers
- Track statistics text overlay
- Scale bar and north arrow

## API Examples

### Single Mission Plot
```http
GET /api/map/plot/m209?hours_back=168&plot_style=detailed&color_by=speed&format=png&dpi=300
```

### Multi-Mission Plot
```http
GET /api/map/plot/multiple?mission_ids=m209,m216&hours_back=72&plot_style=publication&format=pdf
```

### Preview Thumbnail
```http
GET /api/map/plot/preview/m209?hours_back=24&width=5&dpi=72
Response: {"image": "data:image/png;base64,iVBORw0KG..."}
```

## Success Criteria
1. ✅ Generate publication-quality static maps
2. ✅ Support multiple output formats (PNG, SVG, PDF)
3. ✅ Consistent styling with existing plot functions
4. ✅ Reasonable performance (< 5 seconds for standard plots)
5. ✅ Frontend integration with map generator panel
6. ✅ Handle edge cases (empty data, single points, etc.)
7. ✅ Proper UTC timestamp handling (inherit from existing fixes)

