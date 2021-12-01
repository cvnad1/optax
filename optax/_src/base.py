# Copyright 2019 DeepMind Technologies Limited. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Base interfaces and datatypes."""

from typing import Any, Callable, NamedTuple, Optional, Sequence, Tuple

import chex
import jax
import jax.numpy as jnp
import typing_extensions

NO_PARAMS_MSG = (
    'You are using a transformation that requires the current value of '
    'parameters, but you are not passing `params` when calling `update`.')

PyTree = Any
Shape = Sequence[int]

OptState = chex.ArrayTree  # States are arbitrary nests of `jnp.ndarrays`.
Params = chex.ArrayTree  # Parameters are arbitrary nests of `jnp.ndarrays`.
Updates = Params  # Gradient updates are of the same type as parameters.
TransformInitFn = Callable[[Params], OptState]
Schedule = Callable[[chex.Numeric], chex.Numeric]


class TransformUpdateFn(typing_extensions.Protocol):
  """A callable type for computing a new parameters and opt_state pair.

  The params argument is optional, but must be provided when using a
  transformation that requires access to it.
  """

  def __call__(
      self,
      updates: Updates,
      state: OptState,
      params: Optional[Params] = None
    ) -> Tuple[Updates, OptState]:
    ...


class GradientTransformation(NamedTuple):
  """A pair of pure functions implementing a gradient transformation.

  Optax optimizers are all implemented as _gradient transformations_.
  A gradient transformation is defined to be a pair of pure functions, which
  are combined together in a `NamedTuple` so that they can be referred to by
  name.

  Since gradient transformations do not contain any internal state, all stateful
  optimizer properties (such as the current step count when using optimizer
  scheduels, or  momemtum values) are passed through optax gradient
  transformations by using the optimizer _state_ pytree. Each time a gradient
  transformation is applied, a new state is computed and returned, ready to be
  passed to the next call to the gradient transformation.

  Since gradient transformations are pure, idempotent functions, the only way
  to change the behaviour of a gradient transformation between steps, is to
  change the values in the optimizer state. To see an example of mutating the
  optimizer state in order to control the behaviour of an optax gradient
  transformation, see the meta-learning example in the optax documentation.

  Attributes:
    init: A pure function which, when called with an example instance of the
      parameters whose gradients will be transformed, returns a pytree
      containing the initial value for the optimizer state.
    update: A pure function which takes as input a pytree of updates (with the
      same tree structure as the original params pytree passed to init), the
      previous optimizer state (which may have been initialized using the init
      function), and optionally the current params. The update function then
      returns the computed gradient updates, and a new optimizer state.
  """
  init: TransformInitFn
  update: TransformUpdateFn


class EmptyState(NamedTuple):
  """An empty state for the simplest stateless transformations."""


def identity() -> GradientTransformation:
  """Stateless identity transformation that leaves input gradients untouched.

  This function passes through the *gradient updates* unchanged.

  Note, this should not to be confused with `set_to_zero`, which maps the input
  updates to zero - which is the transform required for the *model parameters*
  to be left unchanged when the updates are applied to them.

  Returns:
    An (init_fn, update_fn) tuple.
  """

  def init_fn(_):
    return EmptyState()

  def update_fn(updates, state, params=None):
    del params
    return updates, state

  return GradientTransformation(init_fn, update_fn)


def set_to_zero() -> GradientTransformation:
  """Stateless transformation that maps input gradients to zero.

  The resulting update function, when called, will return a tree of zeros
  matching the shape of the input gradients. This means that when the updates
  returned from this transformation are applied to the model parameters, the
  model parameters will remain unchanged.

  This can be used in combination with `multi_transform` to keep some parts of
  the tree of model parameters fixed while applying gradient updates to other
  parts of the tree.

  Returns:
    An (init_fn, update_fn) tuple.
  """

  def init_fn(params):
    del params
    return EmptyState()

  def update_fn(updates, state, params=None):
    del params  # Unused by the zero transform.
    return jax.tree_map(jnp.zeros_like, updates), state

  return GradientTransformation(init_fn, update_fn)


def stateless(
    f: Callable[[Updates, Optional[Params]], Updates],
    on_leaves: bool=False
) -> GradientTransformation:
  """Creates a stateless GradientTransformation from an update-like function.

  This wrapper eliminates the boilerplate needed to create a transformation that
  does not require saved state between iterations.

  Args:
    f: Update function that takes in updates (e.g. gradients) and parameters
      and returns updates. This function may operate on entire pytrees or on
      individual arrays (i.e. the leaves of updates/params pytrees). The
      parameters may be `None`.
    on_leaves: When `True`, this wrapper will apply `f` to each leaf of the
      updates/params pytrees. When `False`, this wrapper will pass the entire
      updates/params pytrees to `f`.

  Returns:
    An `optax.GradientTransformation`.
  """

  def init_fn(_):
    return EmptyState()

  def update_fn(updates, state, params=None):
    if not on_leaves:
      return f(updates, params), state
    elif params is not None:
      return jax.tree_map(f, updates, params), state
    else:
      f_ = lambda u: f(u, None)
      return jax.tree_map(f_, updates), state

  return GradientTransformation(init_fn, update_fn)
