

data/combined.json:
	sort -o data/combined.json data/psc_data.json data/base_data.json
          
data/export/psc.json: data/combined.json
	mkdir -p data/export
	zavod sorted-merge -o data/export/psc.json data/combined.json