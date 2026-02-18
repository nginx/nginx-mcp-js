#!/usr/bin/env bash
# vim:sw=2:ts=2:sts=2:et
while getopts a:n:u: flag
do
  case "${flag}" in
    a) owner=${OPTARG};;
    n) name=${OPTARG};;
    u) url=${OPTARG};;
    *) echo "Invalid flag: ${flag}"; exit 1;;
  esac
done

echo "Owner: $owner";
echo "Repository Name: $name";
echo "Repository URL: $url";

echo "Renaming repository..."

original_owner="{{REPOSITORY_OWNER}}"
original_name="{{REPOSITORY_NAME}}"
original_url="{{REPOSITORY_URL}}"
for filename in $(git ls-files)
do
  sed -i "s/$original_owner/$owner/g" "$filename"
  sed -i "s/$original_name/$name/g" "$filename"
  sed -i "s/$original_url/$url/g" "$filename"
  echo "Renamed $filename"
done

# These commands run only once on GitHub Actions!
echo "Removing template specific data..."
# Remove OSSF attestations and F5 specific GitHub Actions workflows
rm -f .github/scorecard.yml
if [[ "$GITHUB_REPOSITORY_OWNER" != "devcentral" && "$GITHUB_REPOSITORY_OWNER" != "f5" && "$GITHUB_REPOSITORY_OWNER" != "f5networks" && "$GITHUB_REPOSITORY_OWNER" != "nginx" && "$GITHUB_REPOSITORY_OWNER" != "nginxinc" ]]; then
  rm -f .github/workflows/f5_cla.yml
fi
# Remove the template instructions from the README and the template's CHANGELOG
sed -i '1,/^---$/ { /^$/d; d }' README.md
sed -i '1,/^---$/ { /^$/d; d }' CHANGELOG.md
# Remove Renovatebot and activate Dependabot
rm -f .github/renovate.json
mv .github/dependabot.yml.inactive .github/dependabot.yml
# Remove this script and the GitHub Action workflow using this script
rm -f .github/workflows/rename_template.yml
rm -rf .github/workflows/scripts
