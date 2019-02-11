#!/usr/bin/env python
# coding: utf-8
"""Storing a set of meshes."""
# This file is part of "Capytaine" (https://github.com/mancellin/capytaine).
# It has been written by Matthieu Ancellin and is released under the terms of the GPLv3 license.

import logging
import reprlib
from itertools import chain, accumulate
from typing import Iterable, Union

import numpy as np

from capytaine.mesh.mesh import Mesh
from capytaine.tools.geometry import Abstract3DObject, inplace_transformation

LOG = logging.getLogger(__name__)


class CollectionOfMeshes(Abstract3DObject):
    """A tuple of meshes.
    It gives access to all the vertices of all the sub-meshes as if it were a mesh itself.
    Collections can be nested to store meshes in a tree structure.

    Parameters
    ----------
    meshes: Iterable of Mesh or CollectionOfMeshes
        meshes in the collection
    name : str, optional
        a name for the collection
    """

    def __init__(self, meshes: Iterable[Union[Mesh, 'CollectionOfMeshes']], name=None):

        self._meshes = tuple(meshes)

        for mesh in self._meshes:
            assert isinstance(mesh, Mesh) or isinstance(mesh, CollectionOfMeshes)

        self.name = name

        LOG.debug(f"New collection of meshes: {repr(self)}")

    def __repr__(self):
        reprer = reprlib.Repr()
        reprer.maxstring = 90
        reprer.maxother = 90
        meshes_names = reprer.repr(self._meshes)
        if self.name is not None:
            return f"{self.__class__.__name__}({meshes_names}, name={self.name})"
        else:
            return f"{self.__class__.__name__}{meshes_names}"

    def __str__(self):
        if self.name is not None:
            return self.name
        else:
            return repr(self)

    def __iter__(self):
        return iter(self._meshes)

    def __len__(self):
        return len(self._meshes)

    def __getitem__(self, item):
        return self._meshes.__getitem__(item)

    def __eq__(self, other):
        if isinstance(other, CollectionOfMeshes):
            return self._meshes == other._meshes
        else:
            return NotImplemented

    def __hash__(self):
        return hash(self._meshes)

    def tree_view(self, **kwargs):
        body_tree_views = []
        for i, mesh in enumerate(self):
            tree_view = mesh.tree_view(**kwargs)
            if i == len(self)-1:
                prefix = ' └─'
                shift  = '   '
            else:
                prefix = ' ├─'
                shift  = ' │ '
            body_tree_views.append(prefix + tree_view.replace('\n', '\n' + shift))

        return self.name + '\n' + '\n'.join(body_tree_views)

    def copy(self, name=None):
        from copy import deepcopy
        new_mesh = deepcopy(self)
        if name is not None:
            new_mesh.name = name
        return new_mesh

    ##############
    # Properties #
    ##############

    @property
    def nb_submeshes(self):
        return len(self)

    @property
    def nb_vertices(self):
        return sum(mesh.nb_vertices for mesh in self)

    @property
    def nb_faces(self):
        return sum(mesh.nb_faces for mesh in self)

    @property
    def volume(self):
        return sum(mesh.volume for mesh in self)

    @property
    def vertices(self):
        return np.concatenate([mesh.vertices for mesh in self])

    @property
    def faces(self):
        """Return the indices of the vertices forming each of the faces. For the
        later submeshes, the indices of the vertices has to be shifted to
        correspond to their index in the concatenated array self.vertices.
        """
        nb_vertices = accumulate(chain([0], (mesh.nb_vertices for mesh in self[:-1])))
        return np.concatenate([mesh.faces + nbv for mesh, nbv in zip(self, nb_vertices)])

    @property
    def faces_normals(self):
        return np.concatenate([mesh.faces_normals for mesh in self])

    @property
    def faces_areas(self):
        return np.concatenate([mesh.faces_areas for mesh in self])

    @property
    def faces_centers(self):
        return np.concatenate([mesh.faces_centers for mesh in self])

    @property
    def faces_radiuses(self):
        return np.concatenate([mesh.faces_radiuses for mesh in self])

    @property
    def center_of_mass_of_nodes(self):
        return sum([mesh.nb_vertices*mesh.center_of_mass_of_nodes for mesh in self])/self.nb_vertices

    @property
    def diameter_of_nodes(self):
        return self.merged().diameter_of_nodes  # TODO: improve implementation

    def indices_of_mesh(self, mesh_index: int) -> slice:
        """Return the indices of the faces for the sub-mesh given as argument."""
        start = sum((mesh.nb_faces for mesh in self[:mesh_index]))  # Number of faces in previous meshes
        return slice(start, start + self[mesh_index].nb_faces)

    ##################
    # Transformation #
    ##################

    def merged(self, name=None) -> Mesh:
        """Merge the sub-meshes and return a full mesh.
        If the collection contains other collections, they are merged recursively.
        Optionally, a new name can be given to the resulting mesh."""
        if name is None:
            name = self.name
        merged = Mesh(self.vertices, self.faces, name=name)
        merged.merge_duplicates()
        merged.heal_triangles()
        return merged

    def extract_faces(self, *args, **kwargs):
        return self.merged().extract_faces(*args, **kwargs)

    @inplace_transformation
    def translate(self, vector):
        for mesh in self:
            mesh.translate(vector)

    @inplace_transformation
    def rotate(self, axis, angle):
        for mesh in self:
            mesh.rotate(axis, angle)

    @inplace_transformation
    def mirror(self, plane):
        for mesh in self:
            mesh.mirror(plane)

    @inplace_transformation
    def clip(self, plane):
        self._clipping_data = {'faces_ids': []}
        faces_shifts = list(accumulate(chain([0], (mesh.nb_faces for mesh in self[:-1]))))
        for mesh, faces_shift in zip(self, faces_shifts):
            mesh.clip(plane)
            self._clipping_data['faces_ids'].extend([i + faces_shift for i in mesh._clipping_data['faces_ids']])
        self._clipping_data['faces_ids'] = np.asarray(self._clipping_data['faces_ids'])
        self.prune_empty_meshes()

    def clipped(self, plane, **kwargs):
        # Same API as for the other transformations
        return self.clip(plane, inplace=False, **kwargs)

    def symmetrized(self, plane):
        from capytaine.mesh.symmetries import ReflectionSymmetry
        half = self.clipped(plane, name=f"{self.name}_half")
        return ReflectionSymmetry(half, plane=plane, name=f"symmetrized_of_{self.name}")

    @inplace_transformation
    def keep_immersed_part(self, **kwargs):
        for mesh in self:
            mesh.keep_immersed_part(**kwargs)
        self.prune_empty_meshes()

    @inplace_transformation
    def prune_empty_meshes(self):
        """Remove empty meshes from the collection."""
        self._meshes = tuple(mesh for mesh in self if mesh.nb_faces > 0 and mesh.nb_vertices > 0)

    def show(self, **kwargs):
        from capytaine.ui.vtk.mesh_viewer import MeshViewer

        viewer = MeshViewer()
        for mesh in self:
            viewer.add_mesh(mesh.merged(), **kwargs)
        viewer.show()
        viewer.finalize()

    def show_matplotlib(self, *args, **kwargs):
        self.merged().show_matplotlib(*args, **kwargs)
