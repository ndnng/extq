import numba as nb
import numpy as np

from .. import linalg
from ..moving_semigroup import moving_matmul

__all__ = [
    "forward_extended_committor",
    "forward_extended_mfpt",
    "forward_extended_feynman_kac",
    "backward_extended_committor",
    "backward_extended_mfpt",
    "backward_extended_feynman_kac",
]


def forward_extended_committor(
    basis,
    weights,
    transitions,
    in_domain,
    guess,
    lag,
    test_basis=None,
):
    """Estimate the forward extended committor using DGA.

    Parameters
    ----------
    basis : list of list of (n_frames[i], n_basis) ndarray or sparse matrix of float
        Basis for estimating the extended committor. Must be zero
        outside of the domain. The outer list is over trajectories;
        the inner list is over indices.
    weights : list of (n_frames[i],) ndarray of float
        Change of measure to the invariant distribution for each frame.
    transitions : list of (n_indices, n_indices, n_frames[i]-1) ndarray
        Possible transitions of the index process between adjacent
        frames.
    in_domain : list of (n_indices, n_frames[i]) ndarray of bool
        For each value of the index process, whether each frame of the
        trajectories is in the domain.
    guess : list of (n_indices, n_frames[i]) ndarray of float
        Guess for the extended committor. Must obey boundary conditions.
    lag : int
        DGA lag time in units of frames.
    test_basis : list of list of (n_frames[i], n_basis) ndarray or sparse matrix of float, optional
        Test basis against which to minimize the error. Must have the
        same dimension as the basis used to estimate the extended
        committor. If None, use the basis that is used to estimate the
        extended committor.

    Returns
    -------
    list of (n_indices, n_frames[i]) ndarray of float
        Estimated forward extended committor at each frame.

    """
    return forward_extended_feynman_kac(
        basis,
        weights,
        transitions,
        in_domain,
        np.zeros(len(weights)),
        guess,
        lag,
        test_basis=test_basis,
    )


def forward_extended_mfpt(
    basis,
    weights,
    transitions,
    in_domain,
    guess,
    lag,
    test_basis=None,
):
    """Estimate the forward mean first passage time using DGA.

    Parameters
    ----------
    basis : list of list of (n_frames[i], n_basis) ndarray or sparse matrix of float
        Basis for estimating the mean first passage time . Must be zero
        outside of the domain. The outer list is over trajectories;
        the inner list is over indices.
    weights : list of (n_frames[i],) ndarray of float
        Change of measure to the invariant distribution for each frame.
    transitions : list of (n_indices, n_indices, n_frames[i]-1) ndarray
        Possible transitions of the index process between adjacent
        frames.
    in_domain : list of (n_indices, n_frames[i]) ndarray of bool
        For each value of the index process, whether each frame of the
        trajectories is in the domain.
    guess : list of (n_indices, n_frames[i]) ndarray of float
        Guess for the mean first passage time . Must obey boundary
        conditions.
    lag : int
        DGA lag time in units of frames.
    test_basis : list of list of (n_frames[i], n_basis) ndarray or sparse matrix of float, optional
        Test basis against which to minimize the error. Must have the
        same dimension as the basis used to estimate the mean first
        passage time. If None, use the basis that is used to estimate
        the mean first passage time.

    Returns
    -------
    list of (n_indices, n_frames[i]) ndarray of float
        Estimated forward mean first passage time at each frame.

    """
    return forward_extended_feynman_kac(
        basis,
        weights,
        transitions,
        in_domain,
        np.ones(len(weights)),
        guess,
        lag,
        test_basis=test_basis,
    )


def forward_extended_feynman_kac(
    basis,
    weights,
    transitions,
    in_domain,
    function,
    guess,
    lag,
    test_basis=None,
):
    """Solve the forward Feynman-Kac formula using DGA.

    Parameters
    ----------
    basis : list of list of (n_frames[i], n_basis) ndarray or sparse matrix of float
        Basis for estimating the solution to the Feynman-Kac formula.
        Must be zero outside of the domain. The outer list is over
        trajectories; the inner list is over indices.
    weights : list of (n_frames[i],) ndarray of float
        Change of measure to the invariant distribution for each frame.
    transitions : list of (n_indices, n_indices, n_frames[i]-1) ndarray
        Possible transitions of the index process between adjacent
        frames.
    in_domain : list of (n_indices, n_frames[i]) ndarray of bool
        For each value of the index process, whether each frame of the
        trajectories is in the domain.
    function : list of (n_indices, n_frames[i]-1) ndarray of float
        Function to integrate. Note that this is defined over
        transitions, not frames.
    guess : list of (n_indices, n_frames[i]) ndarray of float
        Guess for the solution. Must obey boundary conditions.
    lag : int
        DGA lag time in units of frames.
    test_basis : list of list of (n_frames[i], n_basis) ndarray or sparse matrix of float, optional
        Test basis against which to minimize the error. Must have the
        same dimension as the basis used to estimate the solution.
        If None, use the basis that is used to estimate the solution.

    Returns
    -------
    list of (n_indices, n_frames[i]) ndarray of float
        Estimate of the solution of the forward Feynman-Kac formulat at
        each frame.

    """
    if test_basis is None:
        test_basis = basis
    a = 0.0
    b = 0.0
    for x, y, w, m, d, f, g in zip(
        test_basis, basis, weights, transitions, in_domain, function, guess
    ):
        assert np.all(w[-lag:] == 0.0)

        ni, _, nt = m.shape
        dtype = np.result_type(*x, *y, w, m, g)
        if np.ndim(f) == 0:
            f = np.full((ni, ni, nt), f, dtype=dtype)

        assert m.shape == (ni, ni, nt)
        assert d.shape == (ni, nt + 1)
        assert f.shape == (ni, ni, nt)
        assert g.shape == (ni, nt + 1)

        m = _forward_transitions_helper(ni, nt, m, d, f, g, lag, dtype)
        m = np.moveaxis(m, 0, -1)

        for i in range(ni):
            wx = linalg.scale_rows(w[:-lag], x[i][:-lag])

            yi = 0.0
            gi = 0.0

            for j in range(ni):
                yi += linalg.scale_rows(m[i, j], y[j][lag:])
                gi += linalg.scale_rows(m[i, j], g[j][lag:])
            gi += m[i, ni]  # integral and boundary conditions

            yi -= y[i][:-lag]
            gi -= g[i][:-lag]

            a += wx.T @ yi
            b -= wx.T @ gi

    coeffs = linalg.solve(a, b)
    return transform(coeffs, basis, guess)


@nb.njit
def _forward_transitions_helper(ni, nt, m, d, f, g, lag, dtype):
    r = np.zeros((nt, ni + 1, ni + 1), dtype=dtype)
    for n in range(nt):
        for i in range(ni):
            if d[i, n]:
                for j in range(ni):
                    r[n, i, j] = m[i, j, n]
                    r[n, i, ni] += m[i, j, n] * f[i, j, n]  # integral
            else:
                r[n, i, ni] = g[i, n]  # boundary conditions
        r[n, ni, ni] = 1.0
    r = moving_matmul(r, lag)
    return r


def backward_extended_committor(
    basis,
    weights,
    transitions,
    in_domain,
    guess,
    lag,
    test_basis=None,
):
    """Estimate the backward extended committor using DGA.

    Parameters
    ----------
    basis : list of list of (n_frames[i], n_basis) ndarray or sparse matrix of float
        Basis for estimating the extended committor. Must be zero
        outside of the domain. The outer list is over trajectories;
        the inner list is over indices.
    weights : list of (n_frames[i],) ndarray of float
        Change of measure to the invariant distribution for each frame.
    transitions : list of (n_indices, n_indices, n_frames[i]-1) ndarray
        Possible transitions of the index process between adjacent
        frames.
    in_domain : list of (n_indices, n_frames[i]) ndarray of bool
        For each value of the index process, whether each frame of the
        trajectories is in the domain.
    guess : list of (n_indices, n_frames[i]) ndarray of float
        Guess for the extended committor. Must obey boundary conditions.
    lag : int
        DGA lag time in units of frames.
    test_basis : list of list of (n_frames[i], n_basis) ndarray or sparse matrix of float, optional
        Test basis against which to minimize the error. Must have the
        same dimension as the basis used to estimate the extended
        committor. If None, use the basis that is used to estimate the
        extended committor.

    Returns
    -------
    list of (n_indices, n_frames[i]) ndarray of float
        Estimated backward extended committor at each frame.

    """
    return backward_extended_feynman_kac(
        basis,
        weights,
        transitions,
        in_domain,
        np.zeros(len(weights)),
        guess,
        lag,
        test_basis=test_basis,
    )


def backward_extended_mfpt(
    basis,
    weights,
    transitions,
    in_domain,
    guess,
    lag,
    test_basis=None,
):
    """Estimate the backward mean first passage time using DGA.

    Parameters
    ----------
    basis : list of list of (n_frames[i], n_basis) ndarray or sparse matrix of float
        Basis for estimating the mean first passage time . Must be zero
        outside of the domain. The outer list is over trajectories;
        the inner list is over indices.
    weights : list of (n_frames[i],) ndarray of float
        Change of measure to the invariant distribution for each frame.
    transitions : list of (n_indices, n_indices, n_frames[i]-1) ndarray
        Possible transitions of the index process between adjacent
        frames.
    in_domain : list of (n_indices, n_frames[i]) ndarray of bool
        For each value of the index process, whether each frame of the
        trajectories is in the domain.
    guess : list of (n_indices, n_frames[i]) ndarray of float
        Guess for the mean first passage time . Must obey boundary
        conditions.
    lag : int
        DGA lag time in units of frames.
    test_basis : list of list of (n_frames[i], n_basis) ndarray or sparse matrix of float, optional
        Test basis against which to minimize the error. Must have the
        same dimension as the basis used to estimate the mean first
        passage time. If None, use the basis that is used to estimate
        the mean first passage time.

    Returns
    -------
    list of (n_indices, n_frames[i]) ndarray of float
        Estimated backward mean first passage time at each frame.

    """
    return backward_extended_feynman_kac(
        basis,
        weights,
        transitions,
        in_domain,
        np.ones(len(weights)),
        guess,
        lag,
        test_basis=test_basis,
    )


def backward_extended_feynman_kac(
    basis,
    weights,
    transitions,
    in_domain,
    function,
    guess,
    lag,
    test_basis=None,
):
    """Solve the backward Feynman-Kac formula using DGA.

    Parameters
    ----------
    basis : list of list of (n_frames[i], n_basis) ndarray or sparse matrix of float
        Basis for estimating the solution to the Feynman-Kac formula.
        Must be zero outside of the domain. The outer list is over
        trajectories; the inner list is over indices.
    weights : list of (n_frames[i],) ndarray of float
        Change of measure to the invariant distribution for each frame.
    transitions : list of (n_indices, n_indices, n_frames[i]-1) ndarray
        Possible transitions of the index process between adjacent
        frames.
    in_domain : list of (n_indices, n_frames[i]) ndarray of bool
        For each value of the index process, whether each frame of the
        trajectories is in the domain.
    function : list of (n_indices, n_frames[i]-1) ndarray of float
        Function to integrate. Note that this is defined over
        transitions, not frames.
    guess : list of (n_indices, n_frames[i]) ndarray of float
        Guess for the solution. Must obey boundary conditions.
    lag : int
        DGA lag time in units of frames.
    test_basis : list of list of (n_frames[i], n_basis) ndarray or sparse matrix of float, optional
        Test basis against which to minimize the error. Must have the
        same dimension as the basis used to estimate the solution.
        If None, use the basis that is used to estimate the solution.

    Returns
    -------
    list of (n_indices, n_frames[i]) ndarray of float
        Estimate of the solution of the backward Feynman-Kac formulat at
        each frame.

    """
    if test_basis is None:
        test_basis = basis
    a = 0.0
    b = 0.0
    for x, y, w, m, d, f, g in zip(
        test_basis, basis, weights, transitions, in_domain, function, guess
    ):
        assert np.all(w[-lag:] == 0.0)

        ni, _, nt = m.shape
        dtype = np.result_type(*x, *y, w, m, g)
        if np.ndim(f) == 0:
            f = np.full((ni, ni, nt), f, dtype=dtype)

        assert m.shape == (ni, ni, nt)
        assert d.shape == (ni, nt + 1)
        assert f.shape == (ni, ni, nt)
        assert g.shape == (ni, nt + 1)

        m = _backward_transitions_helper(ni, nt, m, d, f, g, lag, dtype)
        m = np.moveaxis(m, 0, -1)

        for i in range(ni):
            wx = linalg.scale_rows(w[:-lag], x[i][lag:])

            yi = 0.0
            gi = 0.0

            for j in range(ni):
                yi += linalg.scale_rows(m[j, i], y[j][:-lag])
                gi += linalg.scale_rows(m[j, i], g[j][:-lag])
            gi += m[ni, i]  # integral and boundary conditions

            yi -= y[i][lag:]
            gi -= g[i][lag:]

            a += wx.T @ yi
            b -= wx.T @ gi

    coeffs = linalg.solve(a, b)
    return transform(coeffs, basis, guess)


@nb.njit
def _backward_transitions_helper(ni, nt, m, d, f, g, lag, dtype):
    r = np.zeros((nt, ni + 1, ni + 1), dtype=dtype)
    for n in range(nt):
        for j in range(ni):
            if d[j, n + 1]:
                for i in range(ni):
                    r[n, i, j] = m[i, j, n]
                    r[n, ni, j] += m[i, j, n] * f[i, j, n]  # integral
            else:
                r[n, ni, j] = g[j, n + 1]  # boundary conditions
        r[n, ni, ni] = 1.0
    r = moving_matmul(r, lag)
    return r


def transform(coeffs, basis, guess):
    return [
        np.array([yi @ coeffs + gi for yi, gi in zip(y, g)])
        for y, g in zip(basis, guess)
    ]
