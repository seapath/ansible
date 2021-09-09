# Copyright (C) 2021, RTE (http://www.rte-france.com)
# SPDX-License-Identifier: Apache-2.0
# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys
sys.path.append(os.path.abspath('_extensions'))


# -- Project information -----------------------------------------------------

project = 'vm_cluster'

copyright = 'Copyright (C) 2021, RTE (http://www.rte-france.com)'
author = 'Mathieu Dupré'

# The full version, including alpha/beta/rc tags
release = '0.1'


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = ['sphinx.ext.autodoc', 'sphinx.ext.intersphinx', 'pygments_lexer', 'notfound.extension']

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = []


# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
#html_theme = 'alabaster'

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = 'sphinx'

highlight_language = 'YAML+Jinja'

html_theme_path = ['_themes']
html_theme = 'sphinx_rtd_theme'
html_short_title = 'Ansible Documentation'
html_show_sphinx = False

html_theme_options = {
    'canonical_url': "https://docs.ansible.com/ansible/latest/",
    'vcs_pageview_mode': 'edit'
}

html_context = {
    'display_github': 'False',
    'github_user': 'seapath',
    'github_repo': 'ansible',
    'github_version': 'master',
    'github_module_version': 'master/library/',
    'current_version': 'master',
    'latest_version': 'master',
    # list specifically out of order to make latest work
    'available_versions': ('master'),
    'css_files': ('_static/ansible.css',  # overrides to the standard theme
                  ),
}

# The style sheet to use for HTML and HTML Help pages. A file of that name
# must exist either in Sphinx' static/ path, or in one of the custom paths
# given in html_static_path.
# html_style = 'solar.css'

# The name for this set of Sphinx documents.  If None, it defaults to
# "<project> v<release> documentation".
html_title = 'Ansible Documentation'

# A shorter title for the navigation bar.  Default is the same as html_title.
# html_short_title = None

# The name of an image file (within the static path) to place at the top of
# the sidebar.
# html_logo =

# The name of an image file (within the static path) to use as favicon of the
# docs.  This file should be a Windows icon file (.ico) being 16x16 or 32x32
# pixels large.
# html_favicon = 'favicon.ico'

autoclass_content = 'both'
