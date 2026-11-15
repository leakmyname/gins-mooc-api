.PHONY: setup import serve crawl
setup:
	bash setup.sh
import:
	python3 importer.py
serve:
	python3 server.py
crawl:
	python3 crawler.py
