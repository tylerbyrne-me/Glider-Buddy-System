# Weather Layer Overlay - Implementation Plan

## Feature Overview
Add weather layer overlays to the Leaflet mission track map on the homepage. Users can toggle weather visualizations (clouds, precipitation, wind, pressure, temperature) without affecting track export functionality.

## Requirements
- ✅ Weather layers as visual overlays only (not exportable)
- ✅ Link/attribution to data source
- ✅ Toggle on/off controls
- ✅ No impact on existing map features
- ✅ Lightweight implementation (client-side only)

## Weather Layer Options

### Primary Choice: OpenWeatherMap Tile Layers
**Pros:**
- Free tier available (requires API key but generous limits)
- Multiple layer types: clouds, precipitation, pressure, wind, temperature
- Works directly with Leaflet via tile URLs
- Well-documented

**Layer Types Available:**
1. **Clouds** - `clouds_new` - Shows cloud coverage
2. **Precipitation** - `precipitation_new` - Rain/snow visualization
3. **Pressure** - `pressure_new` - Atmospheric pressure contours
4. **Wind** - `wind_new` - Wind speed and direction
5. **Temperature** - `temp_new` - Temperature overlay

**API Key:**
- Sign up at https://openweathermap.org/api
- Free tier: 1,000 calls/day, 60 calls/minute
- Tile layers don't count against call limits (they're just image tiles)

### Alternative: OpenStreetMap Weather Layers
- No API key required
- Uses OpenWeatherMap data via OSM tile infrastructure
- Limited customization

## Implementation Design

### 1. Frontend Components

#### A. Weather Layer Control UI
- Add weather layer toggle section to map panel
- Multi-select checkboxes for different layer types
- Opacity slider for each layer
- Attribution link to OpenWeatherMap

**Location:** `web/templates/home.html` (map section)

```html
<!-- Weather Layers Control -->
<div class="mt-3 mb-2">
    <div class="d-flex justify-content-between align-items-center mb-2">
        <label class="form-label small mb-0">Weather Overlays</label>
        <a href="https://openweathermap.org/weathermap" target="_blank" class="text-decoration-none small">
            <i class="fas fa-external-link-alt"></i> Data Source
        </a>
    </div>
    <div class="btn-group btn-group-sm" role="group">
        <input type="checkbox" class="btn-check" id="weatherClouds" autocomplete="off">
        <label class="btn btn-outline-primary" for="weatherClouds">Clouds</label>
        
        <input type="checkbox" class="btn-check" id="weatherPrecipitation" autocomplete="off">
        <label class="btn btn-outline-primary" for="weatherPrecipitation">Precipitation</label>
        
        <input type="checkbox" class="btn-check" id="weatherWind" autocomplete="off">
        <label class="btn btn-outline-primary" for="weatherWind">Wind</label>
        
        <input type="checkbox" class="btn-check" id="weatherPressure" autocomplete="off">
        <label class="btn btn-outline-primary" for="weatherPressure">Pressure</label>
        
        <input type="checkbox" class="btn-check" id="weatherTemp" autocomplete="off">
        <label class="btn btn-outline-primary" for="weatherTemp">Temperature</label>
    </div>
    <div class="mt-2">
        <label for="weatherOpacity" class="form-label small">Opacity: <span id="weatherOpacityValue">70%</span></label>
        <input type="range" class="form-range" id="weatherOpacity" min="0" max="100" value="70">
    </div>
</div>
```

#### B. JavaScript Weather Layer Management

**Location:** `web/static/js/map_generator.js`

Functions to add:
1. `initializeWeatherLayers()` - Set up weather layer infrastructure
2. `toggleWeatherLayer(layerType, enabled)` - Add/remove weather layers
3. `updateWeatherOpacity(opacity)` - Adjust all active layers
4. `getWeatherLayerUrl(layerType)` - Construct OpenWeatherMap tile URL

**Implementation Notes:**
- Use Leaflet's `L.tileLayer` for weather overlays
- Store active layers in object: `weatherLayers = {}`
- Apply opacity to each layer
- Use OpenWeatherMap tile URL format:
  ```
  https://tile.openweathermap.org/map/{layer}/{z}/{x}/{y}.png?appid={API_KEY}
  ```

### 2. Configuration

#### A. API Key Management
**Option 1:** Environment Variable (Recommended)
- Add `OPENWEATHERMAP_API_KEY` to `.env`
- Pass to frontend via template context or config endpoint
- Secure: Key stays on server, frontend gets it when needed

**Option 2:** Client-Side Config
- Store in config file or template variable
- Less secure but simpler

**Recommendation:** Use environment variable, pass via secure API endpoint or template context.

#### B. Backend API Endpoint (Optional)
If we want to proxy requests or hide API key:
- `GET /api/map/weather-tiles/{layer}/{z}/{x}/{y}.png`
- Proxies requests to OpenWeatherMap
- Adds API key server-side

**Decision:** Start with direct client-side tiles (API key in config), can add proxy later if needed.

### 3. File Structure

```
web/
├── static/
│   └── js/
│       └── map_generator.js       # Extend with weather layer functions
web/
└── templates/
    └── home.html                  # Add weather layer controls
app/
└── config.py                      # Add OPENWEATHERMAP_API_KEY setting (optional)
```

### 4. Implementation Steps

**Phase 1: Basic Weather Layers**
1. Add weather layer control UI to map panel
2. Implement layer toggle functions in JavaScript
3. Integrate OpenWeatherMap tile layers
4. Add opacity control
5. Add attribution link

**Phase 2: Enhancements (Future)**
1. Layer-specific opacity controls
2. Time selection (current conditions vs forecast)
3. Layer legend/explanation
4. Caching layer tiles for performance

### 5. OpenWeatherMap Tile Layer Details

**Tile URL Format:**
```
https://tile.openweathermap.org/map/{layer}/{z}/{x}/{y}.png?appid={API_KEY}
```

**Available Layers:**
- `clouds_new` - Cloud coverage (0-100%)
- `precipitation_new` - Precipitation intensity
- `pressure_new` - Atmospheric pressure (hPa)
- `wind_new` - Wind speed and direction
- `temp_new` - Temperature (°C)

**Attribution Required:**
- Must include: "Weather data © OpenWeatherMap"

**API Key Setup:**
1. Sign up at https://openweathermap.org/api
2. Get free API key (no credit card required)
3. Add to environment variables
4. Keys are rate-limited but tiles are cached by browsers

### 6. Leaflet Implementation Example

```javascript
// Weather layer configuration
const weatherLayers = {};
const WEATHER_API_KEY = 'YOUR_API_KEY'; // From config

function addWeatherLayer(type) {
    if (weatherLayers[type]) {
        // Already added
        return;
    }
    
    const layer = L.tileLayer(
        `https://tile.openweathermap.org/map/${type}/{z}/{x}/{y}.png?appid=${WEATHER_API_KEY}`,
        {
            attribution: 'Weather data © <a href="https://openweathermap.org">OpenWeatherMap</a>',
            opacity: 0.7,
            maxZoom: 18
        }
    );
    
    weatherLayers[type] = layer;
    layer.addTo(missionMap);
}

function removeWeatherLayer(type) {
    if (weatherLayers[type]) {
        missionMap.removeLayer(weatherLayers[type]);
        delete weatherLayers[type];
    }
}

function updateWeatherOpacity(opacity) {
    Object.values(weatherLayers).forEach(layer => {
        layer.setOpacity(opacity / 100);
    });
}
```

### 7. Alternative: No API Key Solution

If we want to avoid API keys entirely, use **OpenStreetMap Weather Layers**:
- Uses OpenWeatherMap data via OSM infrastructure
- No API key required
- More limited but simpler

**URL Format:**
```
https://{s}.tile.openstreetmap.fr/weather/{z}/{x}/{y}.png
```

## Success Criteria
1. ✅ Weather layers toggle on/off without affecting track data
2. ✅ Multiple layers can be active simultaneously
3. ✅ Opacity control works for all active layers
4. ✅ Attribution link to data source is visible
5. ✅ No performance degradation when layers are active
6. ✅ Layers don't interfere with track export functionality

## Considerations

### Privacy/Security
- API key exposure: If used client-side, it's visible in browser
- Solution: Either accept public API key (free tier is OK) or proxy through backend

### Performance
- Multiple tile layers = more network requests
- Leaflet handles caching automatically
- Consider limiting active layers if performance issues arise

### Rate Limiting
- OpenWeatherMap free tier: 1,000 calls/day
- Tile requests may count (need to verify)
- Monitor usage if high traffic

### Future Enhancements
1. **Marine-specific layers** - Wave height, ocean currents (if available)
2. **Time animation** - Show weather progression over time
3. **Custom legends** - Explain color scales for each layer
4. **Forecast vs Current** - Toggle between current conditions and forecasts
5. **Layer presets** - Quick buttons for common combinations (e.g., "Storm Watch", "Clear Skies")

