.PHONY: \
    gitnexus-init \
    gitnexus-refresh \
    gitnexus-status \
    gitnexus-changes \
    gitnexus-rebuild

gitnexus-init:
	gitnexus analyze --skills
	gitnexus status

gitnexus-refresh:
	./scripts/gitnexus-refresh.sh

gitnexus-status:
	gitnexus status

gitnexus-changes:
	gitnexus detect-changes

gitnexus-rebuild:
	gitnexus analyze --force --skills
	gitnexus status
