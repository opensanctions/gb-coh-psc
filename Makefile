all: data/export/psc.json

data/fragments.json:
	python parse.py

data/combined.json: data/fragments.json
	sort -o data/combined.json data/fragments.json
          
data/export/psc.json: data/combined.json
	mkdir -p data/export
	ftm sorted-aggregate -o data/export/psc.json -i data/combined.json
