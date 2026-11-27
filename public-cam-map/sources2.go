package main

// Additional official, keyless public camera sources + a curated list of public webcam
// pages around Calais / Côte d'Opale (links to the operators' own public pages).

import (
	"bytes"
	"encoding/json"
	"encoding/xml"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"
)

func init() {
	sources = append(sources,
		Source{"fr-opale", "Calais & Côte d'Opale — live players", "FR", "Viewsurf / YouTube live", "Embeddable live players", "", loadOpale, 1e18},
		Source{"fr-vision", "Calais & Coquelles — A16 road cams (shown only when live)", "FR", "Vision-Environnement / DIR Nord", "Public live images", "https://www.vision-environnement.com", loadVision, 30 * time.Minute},
		Source{"es-dgt", "Spain — DGT traffic cameras", "ES", "Dirección General de Tráfico", "DGT open data (NAP)", "https://nap.dgt.es", loadDGT, 120 * 60e9},
		Source{"us-wsdot", "Washington State — WSDOT", "US", "Washington State DOT", "Public (WSDOT)", "https://wsdot.wa.gov", loadWSDOT, 120 * 60e9},
		Source{"ca-drivebc", "British Columbia — DriveBC", "CA", "BC Ministry of Transportation", "Open Government Licence – BC", "https://www.drivebc.ca", loadDriveBC, 120 * 60e9},
		Source{"ca-quebec", "Québec 511 (live video)", "CA", "Ministère des Transports du Québec", "Données Québec (CC BY 4.0)", "https://www.quebec511.info", loadQuebec, 360 * 60e9},
		Source{"us-maryland", "Maryland — CHART (live video)", "US", "Maryland SHA / CHART", "Public (Maryland SHA)", "https://chart.maryland.gov", loadMaryland, 120 * 60e9},
		Source{"is-vegagerdin", "Iceland — Vegagerðin road cams", "IS", "Icelandic Road Administration", "Public (Vegagerðin)", "https://www.vegagerdin.is", loadIceland, 360 * 60e9},
	)
}

// ---------- Calais / Côte d'Opale curated public webcam pages ----------

// Calais / Côte d'Opale: ONLY single-camera live feeds that are made to be embedded
// (Viewsurf's Calais partner player, YouTube live streams). Directory/aggregator pages were
// removed. Viewsurf's other cameras come from the fr-viewsurf source.
var opale = []struct {
	Name  string
	Lat   float64
	Lon   float64
	Embed string // embeddable live player
	Page  string
	City  string
}{
	{"Calais — La Plage (Viewsurf live)", 50.9668, 1.8436, "https://pv.viewsurf.com/1400/Calais", "https://pv.viewsurf.com/1400/Calais", "Calais"},
	{"Sangatte — sea front (YouTube live)", 50.9465, 1.7525, "", "https://www.youtube.com/watch?v=tWJUgV37w2A", "Sangatte"},
	{"Wissant — beach & surf spot (YouTube live)", 50.8865, 1.6620, "https://www.youtube.com/embed/live_stream?channel=UC7IxfHMqwb9_e6r5qa29A4A&autoplay=1&mute=1", "https://www.youtube.com/channel/UC7IxfHMqwb9_e6r5qa29A4A/live", "Wissant"},
}

func loadOpale() ([]Cam, error) {
	var out []Cam
	for i, o := range opale {
		c := Cam{ID: fmt.Sprintf("opale-%d", i), Lat: o.Lat, Lon: o.Lon, Name: o.Name, Video: o.Embed, VType: "iframe", Page: o.Page,
			Kind: "tourism", CC: "FR", City: o.City + ", Pas-de-Calais", Info: "Live player: " + hostOf(o.Embed)}
		if o.Embed == "" { // owner disabled embedding: open its live page in the window over the player
			c.Video, c.VType, c.NoEmbed = o.Page, "window", true
		}
		out = append(out, c)
	}
	return out, nil
}

// ---------- Vision-Environnement road cams around Calais / Coquelles (A16/A216) ----------
// Each publishes one live image. Only cameras whose image was updated in the last 6 hours
// are shown, so frozen feeds never appear as "live".

var visionCams = []struct {
	Slug, Name string
	Lat, Lon   float64
}{
	{"calais-a16-zac-riviere-neuve", "Coquelles / Calais — A16 ZAC Rivière Neuve (Eurotunnel access)", 50.94103, 1.82966},
	{"coulogne-a16-calais", "Coulogne — A16 Calais", 50.93551, 1.87932},
	{"coulogne-a216-calais-marck", "Coulogne — A216 Calais port ↔ Marck", 50.94204, 1.90590},
	{"marck-a16-calais-echangeur-47", "Marck — A16 Calais interchange 47", 50.93643, 1.91459},
	{"marck-a16-calais-echangeur-47-bis", "Marck — A16 Calais interchange 47 bis", 50.93638, 1.91379},
	{"marck-a16-guemps", "Marck — A16 Guemps", 50.93474, 1.98467},
	{"sangatte", "Sangatte — Blériot-Plage", 50.9560, 1.7900},
	{"wissant", "Wissant", 50.8870, 1.6630},
	{"wimereux", "Wimereux", 50.7695, 1.6060},
	{"boulogne", "Boulogne-sur-Mer", 50.7264, 1.5970},
	{"gravelines", "Gravelines", 50.9870, 2.1280},
}

func loadVision() ([]Cam, error) {
	var out []Cam
	var mu sync.Mutex
	var wg sync.WaitGroup
	stale := 0
	for _, v := range visionCams {
		wg.Add(1)
		go func(slug, name string, la, lo float64) {
			defer wg.Done()
			u := "https://www.vision-environnement.com/live/image/webcam/" + slug + ".jpg"
			c := http.Client{Timeout: 15 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
			req, _ := http.NewRequest("HEAD", u, nil)
			req.Header.Set("User-Agent", ua)
			resp, err := c.Do(req)
			if err != nil {
				return
			}
			resp.Body.Close()
			lm, _ := http.ParseTime(resp.Header.Get("Last-Modified"))
			if resp.StatusCode != 200 || lm.IsZero() || time.Since(lm) > 6*time.Hour {
				mu.Lock()
				stale++
				mu.Unlock()
				return
			}
			mu.Lock()
			out = append(out, Cam{ID: "ve-" + slug, Lat: la, Lon: lo, Name: name, Img: u, Kind: "traffic", CC: "FR", City: "Calais area, Pas-de-Calais", Every: 600, Upd: lm.Format(time.RFC3339),
				Page: "https://www.vision-environnement.com/", Info: "Vision-Environnement live image"})
			mu.Unlock()
		}(v.Slug, v.Name, v.Lat, v.Lon)
	}
	wg.Wait()
	if len(out) == 0 {
		return nil, fmt.Errorf("all %d Calais-area road cameras currently frozen/offline at the operator (hidden until they update again)", stale)
	}
	return out, nil
}

// ---------- Spain: DGT DATEX II device publication ----------

func loadDGT() ([]Cam, error) {
	b, err := fetch("https://nap.dgt.es/datex2/v3/dgt/DevicePublication/camaras_datex2_v37.xml", nil)
	if err != nil {
		b, err = fetch("https://nap.dgt.es/datex2/v3/dgt/DevicePublication/camaras_datex2_v36.xml", nil)
		if err != nil {
			return nil, err
		}
	}
	type dev struct {
		ID   string `xml:"id,attr"`
		Type string `xml:"typeOfDevice"`
		Loc  struct {
			Road struct {
				Dest string `xml:"roadDestination"`
				Name string `xml:"roadName"`
			} `xml:"supplementaryPositionalDescription>roadInformation"`
			Lat  float64 `xml:"tpegPointLocation>point>pointCoordinates>latitude"`
			Lon  float64 `xml:"tpegPointLocation>point>pointCoordinates>longitude"`
			KM   string  `xml:"tpegPointLocation>point>_tpegNonJunctionPointExtension>extendedTpegNonJunctionPoint>kilometerPoint"`
			Prov string  `xml:"tpegPointLocation>point>_tpegNonJunctionPointExtension>extendedTpegNonJunctionPoint>province"`
		} `xml:"pointLocation"`
		URL string `xml:"deviceUrl"`
	}
	dec := xml.NewDecoder(bytes.NewReader(b))
	var out []Cam
	for {
		tok, err := dec.Token()
		if err == io.EOF {
			break
		}
		if err != nil {
			break
		}
		se, ok := tok.(xml.StartElement)
		if !ok || se.Name.Local != "device" {
			continue
		}
		var d dev
		if dec.DecodeElement(&d, &se) != nil || d.Type != "camera" || d.URL == "" || d.Loc.Lat == 0 {
			continue
		}
		name := strings.TrimSpace(d.Loc.Road.Name + " km " + d.Loc.KM)
		if d.Loc.Road.Dest != "" {
			name += " → " + d.Loc.Road.Dest
		}
		out = append(out, Cam{ID: "dgt-" + d.ID, Lat: d.Loc.Lat, Lon: d.Loc.Lon, Name: name, Img: d.URL, Kind: "traffic", CC: "ES", City: strings.Title(strings.ToLower(d.Loc.Prov)), Every: 300, Page: "https://infocar.dgt.es/etraffic/"})
	}
	return out, nil
}

func loadWSDOT() ([]Cam, error) {
	b, err := fetch("https://data.wsdot.wa.gov/mobile/Cameras.json", nil)
	if err != nil {
		return nil, err
	}
	var d struct {
		Cameras struct {
			Items []struct {
				ID        int     `json:"id"`
				URL       string  `json:"url"`
				Title     string  `json:"title"`
				Road      string  `json:"roadName"`
				Direction string  `json:"direction"`
				Lat       float64 `json:"lat"`
				Lon       float64 `json:"lon"`
			} `json:"items"`
		} `json:"cameras"`
	}
	if err := json.Unmarshal(b, &d); err != nil {
		return nil, err
	}
	var out []Cam
	for _, c := range d.Cameras.Items {
		out = append(out, Cam{ID: fmt.Sprintf("wsdot-%d", c.ID), Lat: c.Lat, Lon: c.Lon, Name: c.Title, Img: c.URL, Kind: "traffic", CC: "US", City: "Washington State", Info: strings.TrimSpace(c.Road + " " + c.Direction), Every: 120, Page: "https://wsdot.com/travel/real-time/map/"})
	}
	return out, nil
}

func loadDriveBC() ([]Cam, error) {
	b, err := fetch("https://www.drivebc.ca/api/webcams/", nil)
	if err != nil {
		return nil, err
	}
	var d []struct {
		ID      int    `json:"id"`
		Name    string `json:"name"`
		Caption string `json:"caption"`
		Region  string `json:"region_name"`
		Highway string `json:"highway_display"`
		Stale   bool   `json:"marked_stale"`
		Links   struct {
			Img string `json:"imageDisplay"`
		} `json:"links"`
		Location struct {
			Coordinates []float64 `json:"coordinates"`
		} `json:"location"`
		Lat float64 `json:"latitude"`
		Lon float64 `json:"longitude"`
	}
	if err := json.Unmarshal(b, &d); err != nil {
		return nil, err
	}
	var out []Cam
	for _, c := range d {
		la, lo := c.Lat, c.Lon
		if la == 0 && len(c.Location.Coordinates) >= 2 {
			lo, la = c.Location.Coordinates[0], c.Location.Coordinates[1]
		}
		if la == 0 {
			continue
		}
		img := "https://images.drivebc.ca/bchighwaycam/pub/cameras/" + fmt.Sprint(c.ID) + ".jpg"
		if c.Links.Img != "" {
			img = "https://www.drivebc.ca" + strings.Split(c.Links.Img, "?")[0]
		}
		out = append(out, Cam{ID: fmt.Sprintf("bc-%d", c.ID), Lat: la, Lon: lo, Name: c.Name, Img: img, Kind: "traffic", CC: "CA", City: c.Region + ", British Columbia", Info: strings.TrimSpace("Hwy " + c.Highway + " — " + c.Caption), Every: 300, Page: "https://www.drivebc.ca/"})
	}
	return out, nil
}

func loadQuebec() ([]Cam, error) {
	b, err := fetch("https://ws.mapserver.transports.gouv.qc.ca/swtq?service=wfs&version=2.0.0&request=getfeature&typename=ms:infos_cameras&outfile=Camera&srsname=EPSG:4326&outputformat=geojson", nil)
	if err != nil {
		return nil, err
	}
	var d struct {
		Features []struct {
			Geometry struct{ Coordinates []float64 } `json:"geometry"`
			P        struct {
				ID     string `json:"IDEcamera"`
				Num    string `json:"NumeroCamera"`
				DescFr string `json:"DescriptionLocalisationFr"`
				Region string `json:"NomRegionDiffusion"`
				URL    string `json:"URL_FLUX_DONNEE"`
			} `json:"properties"`
		} `json:"features"`
	}
	if err := json.Unmarshal(b, &d); err != nil {
		return nil, err
	}
	var out []Cam
	for _, f := range d.Features {
		if len(f.Geometry.Coordinates) < 2 || f.P.URL == "" {
			continue
		}
		out = append(out, Cam{ID: "qc-" + f.P.ID, Lat: f.Geometry.Coordinates[1], Lon: f.Geometry.Coordinates[0], Name: f.P.DescFr, Video: f.P.URL, VType: "iframe", Page: f.P.URL,
			Kind: "traffic", CC: "CA", City: f.P.Region + ", Québec", Info: "Caméra " + f.P.Num})
	}
	return out, nil
}

func loadMaryland() ([]Cam, error) {
	b, err := fetch("https://chartexp1.sha.maryland.gov/CHARTExportClientService/getCameraMapDataJSON.do", nil)
	if err != nil {
		return nil, err
	}
	var d struct {
		Data []struct {
			ID     string   `json:"id"`
			Name   string   `json:"name"`
			Desc   string   `json:"description"`
			Lat    float64  `json:"lat"`
			Lon    float64  `json:"lon"`
			Comm   string   `json:"commMode"`
			Status string   `json:"opStatus"`
			URL    string   `json:"publicVideoURL"`
			Cat    []string `json:"cameraCategories"`
		} `json:"data"`
	}
	if err := json.Unmarshal(b, &d); err != nil {
		return nil, err
	}
	var out []Cam
	for _, c := range d.Data {
		if c.Comm != "ONLINE" || c.URL == "" {
			continue
		}
		out = append(out, Cam{ID: "md-" + c.ID, Lat: c.Lat, Lon: c.Lon, Name: c.Name, Video: c.URL, VType: "iframe", Page: c.URL, Kind: "traffic", CC: "US",
			City: strings.Join(c.Cat, ", ") + ", Maryland", Info: c.Desc})
	}
	return out, nil
}

func loadIceland() ([]Cam, error) {
	b, err := fetch("https://gagnaveita.vegagerdin.is/api/vefmyndavelar2014_1", nil)
	if err != nil {
		return nil, err
	}
	var d []struct {
		Nr   int     `json:"Maelist_nr"`
		Name string  `json:"Myndavel"`
		Road string  `json:"Vegheiti"`
		Desc string  `json:"Skyring"`
		URL  string  `json:"Slod"`
		Lat  float64 `json:"Breidd"`
		Lon  float64 `json:"Lengd"`
	}
	if err := json.Unmarshal(b, &d); err != nil {
		return nil, err
	}
	var out []Cam
	for i, c := range d {
		if c.URL == "" || c.Lat == 0 {
			continue
		}
		out = append(out, Cam{ID: fmt.Sprintf("is-%d-%d", c.Nr, i), Lat: c.Lat, Lon: c.Lon, Name: c.Name + " — " + c.Desc, Img: c.URL, Kind: "weather", CC: "IS", City: c.Road, Every: 600, Page: "https://umferdin.is/"})
	}
	return out, nil
}
