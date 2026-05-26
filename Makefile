generate:
	REPO_PATH= uv run python3 -m cortexdocs generate --no-eval

generate-phase2:
	uv run python3 -m cortexdocs generate --no-eval

serve:
	uv run python3 -m cortexdocs serve

eval:
	uv run python3 -m cortexdocs eval-docs



deploy:
	uv run mkdocs gh-deploy --config-file output/mkdocs.yml

.PHONY: generate generate-phase2 serve eval deploy
