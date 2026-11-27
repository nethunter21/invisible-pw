package main

// Additional official, keyless public camera sources + a curated list of public webcam
// pages around Calais / Côte d'Opale (links to the operators' own public pages).

import (
	"bytes"
	"encoding/json"
	"encoding/xml"
	"fmt"
	"io"
	"strings"
)

func init() {
	sources = append(sources,
		Source{"fr-opale", "Calais & Côte d'Opale — public webcam pages", "FR", "Webcam owners (Viewsurf, Skyline, tourist offices…)", "Links to public pages", "", loadOpale, 1e18},
		Source{"es-dgt", "Spain — DGT traffic cameras", "ES", "Dirección General de Tráfico", "DGT open data (NAP)", "https://nap.dgt.es", loadDGT, 120 * 60e9},
		Source{"us-wsdot", "Washington State — WSDOT", "US", "Washington State DOT", "Public (WSDOT)", "https://wsdot.wa.gov", loadWSDOT, 120 * 60e9},
		Source{"ca-drivebc", "British Columbia — DriveBC", "CA", "BC Ministry of Transportation", "Open Government Licence – BC", "https://www.drivebc.ca", loadDriveBC, 120 * 60e9},
		Source{"ca-quebec", "Québec 511 (live video)", "CA", "Ministère des Transports du Québec", "Données Québec (CC BY 4.0)", "https://www.quebec511.info", loadQuebec, 360 * 60e9},
		Source{"us-maryland", "Maryland — CHART (live video)", "US", "Maryland SHA / CHART", "Public (Maryland SHA)", "https://chart.maryland.gov", loadMaryland, 120 * 60e9},
		Source{"is-vegagerdin", "Iceland — Vegagerðin road cams", "IS", "Icelandic Road Administration", "Public (Vegagerðin)", "https://www.vegagerdin.is", loadIceland, 360 * 60e9},
	)
}

// ---------- Calais / Côte d'Opale curated public webcam pages ----------

var opale = []struct {
	Name string
	Lat  float64
	Lon  float64
	URL  string
	City string
}{
	{"Calais — La Plage (Viewsurf live)", 50.9668, 1.8436, "https://pv.viewsurf.com/1400/Calais", "Calais"},
	{"Calais — Viewsurf webcams (all Calais views)", 50.9660, 1.8470, "https://m.viewsurf.com/univers/plage/pays/France/region/Nord-Pas-de-Calais/ville/Calais", "Calais"},
	{"Calais — Plage & port, ferries to Dover", 50.9685, 1.8520, "https://calais-dover.com/webcams-weather/", "Calais"},
	{"Calais — Webcams en direct (Calais-Découvrir)", 50.9513, 1.8587, "https://www.calais-decouvrir.fr/live.html", "Calais"},
	{"Calais — View of the beach (SpotCameras)", 50.9672, 1.8380, "https://spotcameras.com/en/cams/Europe/France/18043-Calais-Pas-de-Calais-Hauts-de-France-France-View-of-the-beach", "Calais"},
	{"Calais — Plage (WorldCam)", 50.9664, 1.8405, "https://worldcam.eu/webcams/europe/france/25898-calais-beach", "Calais"},
	{"Calais — Live + timelapse (Webcam Galore)", 50.9675, 1.8460, "https://www.webcamgalore.com/webcam/France/Calais/34684.html", "Calais"},
	{"Calais — Plage (Webcam Galore archive)", 50.9670, 1.8415, "https://www.webcamgalore.com/webcam/France/Calais/32662.html", "Calais"},
	{"Calais — A216 towards the port (traffic)", 50.9510, 1.8960, "https://www.webcam-autoroute.eu/en/cam%C3%A9ras/calais", "Calais"},
	{"Calais — Webcam (MeteoHorizon)", 50.9550, 1.8520, "https://www.meteohorizon.com/europe/france/hauts-de-france/pas-de-calais/calais/webcam", "Calais"},
	{"Calais — Webcam (VaderNu)", 50.9580, 1.8560, "https://www.vadernu.com/europe/france/hauts-de-france/pas-de-calais/calais/webcam", "Calais"},
	{"Calais — Plage de Calais (Windfinder)", 50.9660, 1.8360, "https://www.windfinder.com/webcams/calais_tide", "Calais"},
	{"Calais — Buoy / sea view (Windfinder)", 50.9800, 1.8500, "https://www.windfinder.com/webcams/calais_buoy", "Calais"},
	{"Calais–Dunkerque airport area (Windfinder)", 50.9620, 1.9540, "https://www.windfinder.com/webcams/calais", "Marck"},
	{"Calais — Webcams around Calais (meteoblue)", 50.9500, 1.8600, "https://www.meteoblue.com/en/weather/webcams/calais_france_3029162", "Calais"},
	{"Calais — Webcams in Calais (Outdooractive)", 50.9490, 1.8700, "https://www.outdooractive.com/en/webcams/calais/webcams-in-calais/240895205/", "Calais"},
	{"Sangatte — Plage (SkylineWebcams live)", 50.9465, 1.7525, "https://www.skylinewebcams.com/webcam/france/hauts-de-france/sangatte/plage.html", "Sangatte"},
	{"Sangatte / Blériot-Plage — Vision-Environnement", 50.9560, 1.7900, "https://www.ventusky.com/webcam-652310077", "Sangatte"},
	{"Sangatte — Webcam (WebcamExpo)", 50.9450, 1.7560, "https://webcamexpo.com/webcam-sangatte/", "Sangatte"},
	{"Sangatte — View of the beach (Web Cam Network)", 50.9470, 1.7480, "https://www.the-webcam-network.com/webcam/France/Sangatte/1538.html", "Sangatte"},
	{"Sangatte — Windfinder webcams", 50.9440, 1.7600, "https://www.windfinder.com/webcams/sangatte", "Sangatte"},
	{"Cap Blanc-Nez — surf cam (Surf-forecast)", 50.9265, 1.7150, "https://www.surf-forecast.com/breaks/Cap-Blanc-Nez/webcams/latest", "Escalles"},
	{"Escalles / Cap Blanc-Nez — Windfinder", 50.9170, 1.7150, "https://www.windfinder.com/webcams/escalles_bn", "Escalles"},
	{"Cap Blanc-Nez — webcams around (meteoblue)", 50.9230, 1.7120, "https://www.meteoblue.com/en/weather/webcams/cap-blanc-nez_france_3032371", "Escalles"},
	{"Wissant — Webcam live de la digue (Pays des 2 Caps)", 50.8860, 1.6610, "https://www.paysdes2caps.com/webcam-wissant", "Wissant"},
	{"Wissant — Caméra vue mer (app Pays des 2 Caps)", 50.8870, 1.6630, "https://app.paysdes2caps.com/webcam-live", "Wissant"},
	{"Wissant — surf cam (Surf-forecast)", 50.8890, 1.6580, "https://www.surf-forecast.com/breaks/Wissant/webcams/latest", "Wissant"},
	{"Wimereux — Plage et digue en direct", 50.7695, 1.6060, "https://www.letsgopal.com/en/wimereux-webcam/", "Wimereux"},
	{"Wimereux — Beach (BalticLiveCam)", 50.7710, 1.6040, "https://balticlivecam.com/cameras/france/wimereux/wimereux-beach", "Wimereux"},
	{"Wimereux — webcams around (meteoblue)", 50.7680, 1.6110, "https://www.meteoblue.com/en/weather/webcams/wimereux_france_2967351", "Wimereux"},
	{"Équihen-Plage — webcams du littoral Côte d'Opale", 50.6760, 1.5670, "https://equihenplage.blogspot.com/p/webcam-du-littoral-cote-dopale.html", "Équihen-Plage"},
	{"Le Touquet / Nord-Pas-de-Calais webcams (directory)", 50.5200, 1.5850, "https://www.toutesleswebcams.com/webcams-nord-pas-de-calais.html", "Le Touquet"},
	{"Dunkerque — Live (Viewsurf)", 51.0530, 2.3920, "https://viewsurf.com/univers/surf/vue/16806-france-nord-pas-de-calais-dunkerque-live", "Dunkerque"},
	{"Dunkerque — Mer ouest (Viewsurf)", 51.0520, 2.3850, "https://viewsurf.com/univers/surf/vue/16816-france-nord-pas-de-calais-dunkerque-mer-ouest", "Dunkerque"},
	{"Dunkerque — La passerelle (Viewsurf)", 51.0460, 2.3780, "https://mobile.viewsurf.com/univers/plage/vue/19212-1257489028-france-nord-pas-de-calais-dunkerque-la-passerelle", "Dunkerque"},
	{"Dunkerque — Port de Dunkerque (Viewsurf)", 51.0380, 2.3670, "https://viewsurf.com/univers/plage/vue/16808-france-nord-pas-de-calais-dunkerque-port-de-dunkerque", "Dunkerque"},
	{"Leffrinckoucke (Viewsurf)", 51.0640, 2.4520, "https://mobile.viewsurf.com/univers/plage/vue/16810-france-nord-pas-de-calais-dunkerque-leffrinckoucke", "Leffrinckoucke"},
	{"Zuydcoote — Panoramique HD (Viewsurf)", 51.0760, 2.4900, "https://m.viewsurf.com/univers/plage/vue/18126-1161041964-france-nord-pas-de-calais-zuydcoote-panoramique-hd", "Zuydcoote"},
	{"Bray-Dunes — Live (Viewsurf)", 51.0870, 2.5200, "https://viewsurf.com/univers/plage/vue/16790-france-nord-pas-de-calais-bray-dunes-live", "Bray-Dunes"},
	{"Bray-Dunes — Digue Est (Viewsurf)", 51.0880, 2.5260, "https://m.viewsurf.com/univers/plage/vue/16800-1061240514-france-nord-pas-de-calais-bray-dunes-digue-est", "Bray-Dunes"},
	{"Bray-Dunes — Digue Ouest (Viewsurf)", 51.0860, 2.5140, "https://www.viewsurf.com/univers/plage/vue/16802-france-nord-pas-de-calais-bray-dunes-digue-ouest", "Bray-Dunes"},
	{"Bray-Dunes — Mer Est (Viewsurf)", 51.0895, 2.5240, "https://www.viewsurf.com/univers/plage/vue/16796-france-nord-pas-de-calais-bray-dunes-bray-dunes-mer-est", "Bray-Dunes"},
	{"Bray-Dunes — Mer Ouest (Viewsurf)", 51.0890, 2.5160, "https://www.viewsurf.com/univers/plage/vue/16794-france-nord-pas-de-calais-bray-dunes-mer-ouest", "Bray-Dunes"},
	{"Bray-Dunes — Panoramique HD (Viewsurf)", 51.0875, 2.5190, "https://m.viewsurf.com/univers/plage/vue/16788-1137567784-france-nord-pas-de-calais-bray-dunes-panoramique-hd", "Bray-Dunes"},
}

func loadOpale() ([]Cam, error) {
	var out []Cam
	for i, o := range opale {
		out = append(out, Cam{ID: fmt.Sprintf("opale-%d", i), Lat: o.Lat, Lon: o.Lon, Name: o.Name, Page: o.URL, Kind: "tourism", CC: "FR", City: o.City + ", Pas-de-Calais / Nord",
			Info: "Public webcam page: " + hostOf(o.URL)})
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
