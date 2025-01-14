.. EAGERx documentation master file
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

.. image:: _static/img/banner.png

.. image:: https://img.shields.io/badge/License-Apache_2.0-blue.svg
   :target: https://opensource.org/licenses/Apache-2.0
   :alt: license

.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
   :target: https://github.com/psf/black
   :alt: codestyle

.. image:: https://readthedocs.org/projects/eagerx/badge/?version=master
   :target: https://eagerx.readthedocs.io/en/master/?badge=master
   :alt: Documentation Status

.. image:: https://github.com/eager-dev/eagerx/actions/workflows/ci.yml/badge.svg?branch=master
   :target: https://github.com/eager-dev/eagerx/actions/workflows/ci.yml
   :alt: Continuous Integration

.. image:: https://api.codeclimate.com/v1/badges/3146dce3dd4c3537834c/test_coverage
   :target: https://codeclimate.com/github/eager-dev/eagerx/test_coverage
   :alt: Test Coverage

|

What is EAGERx
==============
`EAGERx <https://github.com/eager-dev/eagerx>`_ (Engine Agnostic Gym Environments for Robotics) enables users to
easily define new tasks, switch from one sensor to another,
and switch from simulation to reality with a single line of code by being invariant to the physics engine.
EAGERx explicitly addresses the differences in learning between simulation and reality,
with essential features for roboticists such as a safety layer, signal delay simulation, and controller switching for resets.
A single RL pipeline that works with both the simulated and real robots eliminates the chance for mismatches between the simulation and reality implementation.
The defined task follows the OpenAI Gym interface, so one can plug in algorithms from established RL libraries
(e.g., `Stable-baselines3 <https://github.com/DLR-RM/stable-baselines3>`_ ) to solve the task afterward, again minimizing implementation errors.

..
    TODO: ADD code example with gifs?
    Example
    =================

.. toctree::
   :maxdepth: 2
   :caption: Table of Contents

   guide/getting_started/index

   guide/tutorials/index

   guide/developer_guide/index

   guide/api_reference/index

   guide/examples/index

   guide/troubleshooting/index

   guide/contributing/index

Cite EAGERx
===========
If you are using EAGERx for your scientific publications, please cite:

.. code:: bibtex

    @article{eagerx,
        author  = {van der Heijden, Bas and Luijkx, Jelle, and Ferranti, Laura and Kober, Jens and Babuska, Robert},
        title = {EAGER: Engine Agnostic Gym Environment for Robotics},
        year = {2022},
        publisher = {GitHub},
        journal = {GitHub repository},
        howpublished = {\url{https://github.com/eager-dev/eagerx}}
    }

Maintainers
===========
EAGERx is currently maintained by Bas van der Heijden (`@bheijden <https://github.com/bheijden>`_) and Jelle Luijkx (`@jelledouwe <https://github.com/jelledouwe>`_).

How to contact us
=================
Follow us on Twitter `@EagerxD <https://twitter.com/EagerxD>`_!

For any question, send an e-mail to eagerx.dev@gmail.com.

Acknowledgements
================
EAGERx is funded by the `OpenDR <https://opendr.eu/>`_ Horizon 2020 project.
