generate:
	python3 -m cortexdocs generate

generate-phase1:
	python3 -m cortexdocs generate --no-eval

serve:
	python3 -m cortexdocs serve

eval:
	python3 -m cortexdocs eval-docs

deploy:
	mkdocs gh-deploy --config-file output/mkdocs.yml

.PHONY: generate generate-phase1 serve eval deploy
