.PHONY: install test demo run clean
install:
	python -m pip install -r requirements.txt && python -m playwright install chromium
test:
	python -m pytest
demo:            ## offline run on SYNTHETIC data (seconds)
	python -m btli demo
run:             ## real run: download, extract, analyse, report
	python -m btli all
clean:
	rm -rf output output_demo .pytest_cache
