

data/combined.json:
	sort -o data/combined.json data/psc_data.json data/base_data.json
          
data/export/psc.json: data/combined.json
	mkdir -p data/export
	ftm sorted-aggregate -o data/export/psc.json -i data/combined.json