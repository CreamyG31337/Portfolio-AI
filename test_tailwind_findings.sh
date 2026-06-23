#!/bin/bash
echo "== Checking for \@apply in web_dashboard/static/css/input.css =="
grep -n "\@apply" web_dashboard/static/css/input.css

echo "== Checking for inline styles that could be utility classes =="
grep -rn "style=" web_dashboard/templates/ | grep -v "/email/" | grep -v "digest" | grep -v "width" | head -n 20

echo "== Checking for non-Flowbite custom modals/dropdowns/etc =="
grep -rn ".classList.toggle('hidden')" web_dashboard/src/js/ | head -n 10
