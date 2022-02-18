SHELL=/bin/bash
LINT_PATHS=eagerx/

pytest:
	bash ./scripts/run_tests.sh

check-codestyle:
	# Reformat using black
	poetry run black --check -l 127 ${LINT_PATHS}

lint:
	# stop the build if there are Python syntax errors or undefined names
	# see https://lintlyci.github.io/Flake8Rules/
	poetry run flake8 ${LINT_PATHS} --count --select=E9,F63,F7,F82 --show-source --statistics
	# exit-zero treats all errors as warnings.
	poetry run flake8 ${LINT_PATHS} --count --exit-zero --statistics

# Make docs
doc:
	cd docs && make html

spelling:
	cd docs && make spelling

clean:
	cd docs && make clean

# PyPi package release
#release:
	#python setup.py sdist
	#python setup.py bdist_wheel
	#twine upload dist/*

# Test PyPi package release
#test-release:
	#python setup.py sdist
	#python setup.py bdist_wheel
	#twine upload --repository-url https://test.pypi.org/legacy/ dist/*


.PHONY: check-codestyle