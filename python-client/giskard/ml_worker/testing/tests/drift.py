import re
import typing
import uuid
from collections import Counter
from typing import Union

import numpy as np
import pandas as pd
from scipy.stats import chi2, ks_2samp
from scipy.stats.stats import Ks_2sampResult, wasserstein_distance

from giskard.core.core import SupportedModelTypes
from giskard.datasets.base import Dataset
from giskard.ml_worker.core.test_result import TestResult
from giskard.ml_worker.generated.ml_worker_pb2 import TestMessage, TestMessageType
from giskard.ml_worker.testing.registry.decorators import test
from giskard.models.base import BaseModel

other_modalities_pattern = "^other_modalities_[a-z0-9]{32}$"


def _calculate_psi(category, actual_distribution, expected_distribution):
    # To use log and avoid zero distribution probability,
    # we bound distribution probability by min_distribution_probability
    min_distribution_probability = 0.0001

    expected_distribution_bounded = max(expected_distribution[category], min_distribution_probability)
    actual_distribution_bounded = max(actual_distribution[category], min_distribution_probability)
    modality_psi = (expected_distribution_bounded - actual_distribution_bounded) * np.log(
        expected_distribution_bounded / actual_distribution_bounded
    )
    return modality_psi


def _calculate_frequencies(actual_series, reference_series, max_categories=None):
    all_modalities = list(set(reference_series).union(set(actual_series)))
    if max_categories is not None and len(all_modalities) > max_categories:
        var_count_expected = dict(Counter(reference_series).most_common(max_categories))
        other_modalities_key = "other_modalities_" + uuid.uuid1().hex
        var_count_expected[other_modalities_key] = len(reference_series) - sum(var_count_expected.values())
        categories_list = list(var_count_expected.keys())

        var_count_actual = Counter(actual_series)
        # For test data, we take the same category names as expected_data
        var_count_actual = {i: var_count_actual[i] for i in categories_list}
        var_count_actual[other_modalities_key] = len(actual_series) - sum(var_count_actual.values())

        all_modalities = categories_list
    else:
        var_count_expected = Counter(reference_series)
        var_count_actual = Counter(actual_series)
    expected_frequencies = np.array([var_count_expected[i] for i in all_modalities])
    actual_frequencies = np.array([var_count_actual[i] for i in all_modalities])
    return all_modalities, actual_frequencies, expected_frequencies


def _calculate_drift_psi(actual_series, reference_series, max_categories):
    (
        all_modalities,
        actual_frequencies,
        expected_frequencies,
    ) = _calculate_frequencies(actual_series, reference_series, max_categories)
    expected_distribution = expected_frequencies / len(reference_series)
    actual_distribution = actual_frequencies / len(actual_series)
    total_psi = 0
    output_data = pd.DataFrame(columns=["Modality", "Reference_distribution", "Actual_distribution", "Psi"])
    for category in range(len(all_modalities)):
        modality_psi = _calculate_psi(category, actual_distribution, expected_distribution)

        total_psi += modality_psi
        row = {
            "Modality": all_modalities[category],
            "Reference_distribution": expected_distribution[category],
            "Actual_distribution": expected_distribution[category],
            "Psi": modality_psi,
        }

        output_data = output_data.append(pd.Series(row), ignore_index=True)
    return total_psi, output_data


def _calculate_ks(actual_series, reference_series) -> Ks_2sampResult:
    return ks_2samp(reference_series, actual_series)


def _calculate_earth_movers_distance(actual_series, reference_series):
    unique_reference = np.unique(reference_series)
    unique_actual = np.unique(actual_series)
    sample_space = list(set(unique_reference).union(set(unique_actual)))
    val_max = max(sample_space)
    val_min = min(sample_space)
    if val_max == val_min:
        metric = 0
    else:
        # Normalizing reference_series and actual_series for comparison purposes
        reference_series = (reference_series - val_min) / (val_max - val_min)
        actual_series = (actual_series - val_min) / (val_max - val_min)

        metric = wasserstein_distance(reference_series, actual_series)
    return metric


def _calculate_chi_square(actual_series, reference_series, max_categories):
    (
        all_modalities,
        actual_frequencies,
        expected_frequencies,
    ) = _calculate_frequencies(actual_series, reference_series, max_categories)
    chi_square = 0
    # it's necessary for comparison purposes to normalize expected_frequencies
    # so that reference and actual has the same size
    # See https://github.com/scipy/scipy/blob/v1.8.0/scipy/stats/_stats_py.py#L6787
    k_norm = actual_series.shape[0] / reference_series.shape[0]
    output_data = pd.DataFrame(columns=["Modality", "Reference_frequencies", "Actual_frequencies", "Chi_square"])
    for i in range(len(all_modalities)):
        chi_square_value = (actual_frequencies[i] - expected_frequencies[i] * k_norm) ** 2 / (
                expected_frequencies[i] * k_norm
        )
        chi_square += chi_square_value

        row = {
            "Modality": all_modalities[i],
            "Reference_frequencies": expected_frequencies[i],
            "Actual_frequencies": actual_frequencies[i],
            "Chi_square": chi_square_value,
        }

        output_data = output_data.append(pd.Series(row), ignore_index=True)
    # if reference_series and actual_series has only one modality it turns nan (len(all_modalities)=1)
    if len(all_modalities) > 1:
        chi_cdf = chi2.cdf(chi_square, len(all_modalities) - 1)
        p_value = 1 - chi_cdf if chi_cdf != 0 else 0
    else:
        p_value = 0
    return chi_square, p_value, output_data


def _validate_feature_type(gsk_dataset, column_name, feature_type):
    assert (
            gsk_dataset.feature_types[column_name] == feature_type
    ), f'Column "{column_name}" is not of type "{feature_type}"'


def _validate_column_name(actual_ds, reference_ds, column_name):
    assert (
            column_name in actual_ds.columns
    ), f'"{column_name}" is not a column of Actual Dataset Columns: {", ".join(actual_ds.columns)}'
    assert (
            column_name in reference_ds.columns
    ), f'"{column_name}" is not a column of Reference Dataset Columns: {", ".join(reference_ds.columns)}'


def _validate_series_notempty(actual_series, reference_series):
    if actual_series.empty:
        raise ValueError("Actual Series computed from the column is empty")
    if reference_series.empty:
        raise ValueError("Reference Series computed from the column is empty")


def _extract_series(actual_ds, reference_ds, column_name, feature_type):
    actual_ds.df.reset_index(drop=True, inplace=True)
    reference_ds.df.reset_index(drop=True, inplace=True)
    _validate_column_name(actual_ds, reference_ds, column_name)
    _validate_feature_type(actual_ds, column_name, feature_type)
    _validate_feature_type(reference_ds, column_name, feature_type)
    actual_series = actual_ds.df[column_name]
    reference_series = reference_ds.df[column_name]
    _validate_series_notempty(actual_series, reference_series)
    return actual_series, reference_series


@test(name='Categorical drift (PSI)')
def test_drift_psi(
        reference_ds: Dataset,
        actual_ds: Dataset,
        column_name: str,
        threshold: float = 0.2,
        max_categories: int = 20,
        psi_contribution_percent: float = 0.2,
) -> TestResult:
    """
    Test if the PSI score between the actual and reference datasets is below the threshold for
    a given categorical feature

    Example : The test is passed when the  PSI score of gender between reference and actual sets is below 0.2

    Args:
        actual_ds:
            Actual dataset to compute the test
        reference_ds:
            Reference dataset to compute the test
        column_name:
            Name of column with categorical feature
        threshold:
            Threshold value for PSI
        max_categories:
            the maximum categories to compute the PSI score
        psi_contribution_percent:
            the ratio between the PSI score of a given category over the total PSI score
            of the categorical variable. If there is a drift, the test provides all the
            categories that have a PSI contribution over than this ratio.

    Returns:
        actual_slices_size:
            Length of rows with given categorical feature in actual slice
        reference_slices_size:
            Length of rows with given categorical feature in reference slice
        metric:
            The total psi score between the actual and reference datasets
        passed:
            TRUE if total_psi <= threshold
    """
    actual_series, reference_series = _extract_series(actual_ds, reference_ds, column_name, "category")

    messages, passed, total_psi = _test_series_drift_psi(
        actual_series,
        reference_series,
        "data",
        max_categories,
        psi_contribution_percent,
        threshold,
    )

    return TestResult(
        actual_slices_size=[len(actual_series)],
        reference_slices_size=[len(reference_series)],
        passed=passed,
        metric=total_psi,
        messages=messages,
    )


@test(name='Categorical drift (Chi-squared)')
def test_drift_chi_square(
        reference_ds: Dataset,
        actual_ds: Dataset,
        column_name: str,
        threshold: float = 0.05,
        max_categories: int = 20,
        chi_square_contribution_percent: float = 0.2,
) -> TestResult:
    """
    Test if the p-value of the chi square test between the actual and reference datasets is
    above the threshold for a given categorical feature

    Example : The test is passed when the pvalue of the chi square test of the categorical variable between
     reference and actual sets is higher than 0.05. It means that chi square test cannot be rejected at 5% level
     and that we cannot assume drift for this variable.

    Args:
        actual_ds(Dataset):
            Actual dataset to compute the test
        reference_ds(Dataset):
            Reference dataset to compute the test
        column_name(str):
            Name of column with categorical feature
        threshold(float):
            Threshold for p-value of chi-square
        max_categories:
            the maximum categories to compute the chi square
        chi_square_contribution_percent:
            the ratio between the Chi-Square value of a given category over the total Chi-Square
            value of the categorical variable. If there is a drift, the test provides all the
            categories that have a PSI contribution over than this ratio.

    Returns:
        actual_slices_size:
            Length of rows with given categorical feature in actual slice
        reference_slices_size:
            Length of rows with given categorical feature in reference slice
        metric:
            The pvalue of chi square test
        passed:
            TRUE if metric > threshold
    """
    actual_series, reference_series = _extract_series(actual_ds, reference_ds, column_name, "category")

    messages, p_value, passed = _test_series_drift_chi(
        actual_series,
        reference_series,
        "data",
        chi_square_contribution_percent,
        max_categories,
        threshold,
    )

    return TestResult(
        actual_slices_size=[len(actual_series)],
        reference_slices_size=[len(reference_series)],
        passed=passed,
        metric=p_value,
        messages=messages,
    )


@test(name='Numerical drift (Kolmogorov-Smirnov)')
def test_drift_ks(
        reference_ds: Dataset,
        actual_ds: Dataset,
        column_name: str,
        threshold: float = 0.05,
) -> TestResult:
    """
    Test if the pvalue of the KS test between the actual and reference datasets is above
    the threshold for a given numerical feature

    Example : The test is passed when the pvalue of the KS test of the numerical variable
    between the actual and reference datasets is higher than 0.05. It means that the KS test
    cannot be rejected at 5% level and that we cannot assume drift for this variable.

    Args:
        actual_ds(Dataset):
           Actual dataset to compute the test
        reference_ds(Dataset):
            Reference dataset to compute the test
        column_name(str):
            Name of column with numerical feature
        threshold:
            Threshold for p-value of KS test

    Returns:
        actual_slices_size:
            Length of rows with given numerical feature in actual slice
        reference_slices_size:
            Length of rows with given numerical feature in reference slice
        metric:
            The pvalue of KS test
        passed:
            TRUE if metric >= threshold
    """
    actual_series, reference_series = _extract_series(actual_ds, reference_ds, column_name, "numeric")

    result = _calculate_ks(actual_series, reference_series)

    passed = bool(result.pvalue >= threshold)

    messages = _generate_message_ks(passed, result, threshold, "data")

    return TestResult(
        actual_slices_size=[len(actual_series)],
        reference_slices_size=[len(reference_series)],
        passed=passed,
        metric=result.pvalue,
        messages=messages
    )


@test(name='Numerical drift (Earth mover\'s distance)')
def test_drift_earth_movers_distance(
        reference_ds: Dataset,
        actual_ds: Dataset,
        column_name: str,
        threshold: float = 0.2,
) -> TestResult:
    """
    Test if the earth movers distance between the actual and reference datasets is
    below the threshold for a given numerical feature

    Example : The test is passed when the earth movers distance of the numerical
     variable between the actual and reference datasets is lower than 0.1.
     It means that we cannot assume drift for this variable.

    Args:
        actual_ds(Dataset):
            Actual dataset to compute the test
        reference_ds(Dataset):
            Reference dataset to compute the test
        column_name(str):
            Name of column with numerical feature
        threshold:
            Threshold for earth movers distance

    Returns:
        actual_slices_size:
            Length of rows with given numerical feature in actual slice
        reference_slices_size:
            Length of rows with given numerical feature in reference slice
        metric:
            The earth movers distance
        passed:
            TRUE if metric <= threshold
    """
    actual_series, reference_series = _extract_series(actual_ds, reference_ds, column_name, "numeric")

    metric = _calculate_earth_movers_distance(actual_series, reference_series)

    passed = bool(metric <= threshold)

    messages: Union[typing.List[TestMessage], None] = None

    if not passed:
        messages = [
            TestMessage(
                type=TestMessageType.ERROR,
                text=f"The data is drifting (metric is equal to {np.round(metric, 9)} and is below the test risk level {threshold}) ",
            )
        ]
    return TestResult(
        actual_slices_size=[len(actual_series)],
        reference_slices_size=[len(reference_series)],
        passed=True if threshold is None else passed,
        metric=metric,
        messages=messages,
    )


@test(name='Label drift (PSI)')
def test_drift_prediction_psi(
        reference_slice: Dataset,
        actual_slice: Dataset,
        model: BaseModel,
        max_categories: int = 10,
        threshold: float = 0.2,
        psi_contribution_percent: float = 0.2,
):
    """
    Test if the PSI score between the reference and actual datasets is below the threshold
    for the classification labels predictions

    Example : The test is passed when the  PSI score of classification labels prediction
    for females between reference and actual sets is below 0.2

    Args:
        actual_slice(Dataset):
            Slice of the actual dataset
        reference_slice(Dataset):
            Slice of the reference dataset
        model(BaseModel):
            Model used to compute the test
        threshold(float):
            Threshold value for PSI
        max_categories:
            The maximum categories to compute the PSI score
        psi_contribution_percent:
            The ratio between the PSI score of a given category over the total PSI score
            of the categorical variable. If there is a drift, the test provides all the
            categories that have a PSI contribution over than this ratio.

    Returns:
        actual_slices_size:
            Length of actual slice tested
        reference_slices_size:
            Length of reference slice tested
        passed:
            TRUE if metric <= threshold
        metric:
            Total PSI value
        messages:
            Psi result message
    """
    actual_slice.df.reset_index(drop=True, inplace=True)
    reference_slice.df.reset_index(drop=True, inplace=True)
    prediction_reference = pd.Series(model.predict(reference_slice).prediction)
    prediction_actual = pd.Series(model.predict(actual_slice).prediction)
    messages, passed, total_psi = _test_series_drift_psi(
        prediction_actual,
        prediction_reference,
        "prediction",
        max_categories,
        psi_contribution_percent,
        threshold,
    )

    return TestResult(
        actual_slices_size=[len(actual_slice)],
        reference_slices_size=[len(reference_slice)],
        passed=passed,
        metric=total_psi,
        messages=messages,
    )


def _test_series_drift_psi(
        actual_series,
        reference_series,
        test_data,
        max_categories,
        psi_contribution_percent,
        threshold,
):
    total_psi, output_data = _calculate_drift_psi(actual_series, reference_series, max_categories)
    passed = True if threshold is None else bool(total_psi <= threshold)
    main_drifting_modalities_bool = output_data["Psi"] > psi_contribution_percent * total_psi
    messages = _generate_message_modalities(main_drifting_modalities_bool, output_data, test_data)
    return messages, passed, total_psi


def _generate_message_modalities(main_drifting_modalities_bool, output_data, test_data):
    modalities_list = output_data[main_drifting_modalities_bool]["Modality"].tolist()
    filtered_modalities = [w for w in modalities_list if not re.match(other_modalities_pattern, w)]
    messages: Union[typing.List[TestMessage], None] = None
    if filtered_modalities:
        messages = [
            TestMessage(
                type=TestMessageType.ERROR,
                text=f"The {test_data} is drifting for the following modalities: {','.join(filtered_modalities)}",
            )
        ]
    return messages


@test(name='Label drift (Chi-squared)')
def test_drift_prediction_chi_square(
        reference_slice: Dataset,
        actual_slice: Dataset,
        model: BaseModel,
        max_categories: int = 10,
        threshold: float = 0.05,
        chi_square_contribution_percent: float = 0.2,
):
    """
    Test if the Chi Square value between the reference and actual datasets is below the threshold
    for the classification labels predictions for a given slice

    Example : The test is passed when the  Chi Square value of classification labels prediction
    for females between reference and actual sets is below 0.05

    Args:
        actual_slice(Dataset):
            Slice of the actual dataset
        reference_slice(Dataset):
            Slice of the reference dataset
        model(BaseModel):
            Model used to compute the test
        threshold(float):
            Threshold value of p-value of Chi-Square
        max_categories:
            the maximum categories to compute the PSI score
        chi_square_contribution_percent:
            the ratio between the Chi-Square value of a given category over the total Chi-Square
            value of the categorical variable. If there is a drift, the test provides all the
            categories that have a PSI contribution over than this ratio.

    Returns:
        actual_slices_size:
            Length of actual slice tested
        reference_slices_size:
            Length of reference slice tested
        passed:
            TRUE if metric > threshold
        metric:
            Calculated p-value of Chi_square
        messages:
            Message describing if prediction is drifting or not
    """
    actual_slice.df.reset_index(drop=True, inplace=True)
    reference_slice.df.reset_index(drop=True, inplace=True)
    prediction_reference = pd.Series(model.predict(reference_slice).prediction)
    prediction_actual = pd.Series(model.predict(actual_slice).prediction)

    messages, p_value, passed = _test_series_drift_chi(
        prediction_actual,
        prediction_reference,
        "prediction",
        chi_square_contribution_percent,
        max_categories,
        threshold,
    )

    return TestResult(
        actual_slices_size=[len(actual_slice)],
        reference_slices_size=[len(reference_slice)],
        passed=passed,
        metric=p_value,
        messages=messages,
    )


def _test_series_drift_chi(
        actual_series,
        reference_series,
        test_data,
        chi_square_contribution_percent,
        max_categories,
        threshold,
):
    chi_square, p_value, output_data = _calculate_chi_square(actual_series, reference_series, max_categories)
    passed = bool(p_value > threshold)
    main_drifting_modalities_bool = output_data["Chi_square"] > chi_square_contribution_percent * chi_square
    messages = _generate_message_modalities(main_drifting_modalities_bool, output_data, test_data)
    return messages, p_value, passed


@test(name='Classification Probability drift (Kolmogorov-Smirnov)', tags=['classification'])
def test_drift_prediction_ks(
        reference_slice: Dataset,
        actual_slice: Dataset,
        model: BaseModel,
        classification_label: str = None,
        threshold: float = None,
) -> TestResult:
    """
    Test if the pvalue of the KS test for prediction between the reference and actual datasets for
     a given subpopulation is above the threshold

    Example : The test is passed when the pvalue of the KS test for the prediction for females
     between reference and actual dataset is higher than 0.05. It means that the KS test cannot be
     rejected at 5% level and that we cannot assume drift for this variable.

    Args:
        actual_slice(Dataset):
            Slice of the actual dataset
        reference_slice(Dataset):
            Slice of the reference dataset
        model(BaseModel):
            Model used to compute the test
        threshold(float):
            Threshold for p-value of Kolmogorov-Smirnov test
        classification_label(str):
            One specific label value from the target column for classification model

    Returns:
        actual_slices_size:
            Length of actual slice tested
        reference_slices_size:
            Length of reference slice tested
        passed:
            TRUE if metric >= threshold
        metric:
            The calculated p-value Kolmogorov-Smirnov test
        messages:
            Kolmogorov-Smirnov result message
    """
    actual_slice.df.reset_index(drop=True, inplace=True)
    reference_slice.df.reset_index(drop=True, inplace=True)

    assert (
            model.meta.model_type != SupportedModelTypes.CLASSIFICATION
            or classification_label in model.meta.classification_labels
    ), f'"{classification_label}" is not part of model labels: {",".join(model.meta.classification_labels)}'

    prediction_reference = (
        pd.Series(model.predict(reference_slice).all_predictions[classification_label].values)
        if model.is_classification
        else pd.Series(model.predict(reference_slice).prediction)
    )
    prediction_actual = (
        pd.Series(model.predict(actual_slice).all_predictions[classification_label].values)
        if model.is_classification
        else pd.Series(model.predict(actual_slice).prediction)
    )

    result: Ks_2sampResult = _calculate_ks(prediction_reference, prediction_actual)

    passed = True if threshold is None else bool(result.pvalue >= threshold)

    messages = _generate_message_ks(passed, result, threshold, "prediction")

    return TestResult(
        actual_slices_size=[len(actual_slice)],
        reference_slices_size=[len(reference_slice)],
        passed=passed,
        metric=result.pvalue,
        messages=messages,
    )


def _generate_message_ks(passed, result, threshold, data_type):
    messages: Union[typing.List[TestMessage], None] = None
    if not passed:
        messages = [
            TestMessage(
                type=TestMessageType.ERROR,
                text=f"The {data_type} is drifting (p-value is equal to {np.round(result.pvalue, 9)} "
                     f"and is below the test risk level {threshold}) ",
            )
        ]
    return messages


@test(name='Classification Probability drift (Earth mover\'s distance)', tags=['classification'])
def test_drift_prediction_earth_movers_distance(
        reference_slice: Dataset,
        actual_slice: Dataset,
        model: BaseModel,
        classification_label: str = None,
        threshold: float = 0.2,
) -> TestResult:
    """
    Test if the Earth Mover’s Distance value between the reference and actual datasets is
    below the threshold for the classification labels predictions for classification
    model and prediction for regression models

    Example :
    Classification : The test is passed when the  Earth Mover’s Distance value of classification
    labels probabilities for females between reference and actual sets is below 0.2

    Regression : The test is passed when the  Earth Mover’s Distance value of prediction
    for females between reference and actual sets is below 0.2

    Args:
        reference_slice(Dataset):
            slice of the reference dataset
        actual_slice(Dataset):
            slice of the actual dataset
        model(BaseModel):
            uploaded model
        classification_label:
            one specific label value from the target column for classification model
        threshold:
            threshold for earth mover's distance

    Returns:
        passed:
            TRUE if metric <= threshold
        metric:
            Earth Mover's Distance value

    """
    actual_slice.df.reset_index(drop=True, inplace=True)
    reference_slice.df.reset_index(drop=True, inplace=True)

    prediction_reference = (
        model.predict(reference_slice).all_predictions[classification_label].values
        if model.is_classification
        else model.predict(reference_slice).prediction
    )
    prediction_actual = (
        model.predict(actual_slice).all_predictions[classification_label].values
        if model.is_classification
        else model.predict(actual_slice).prediction
    )

    metric = _calculate_earth_movers_distance(prediction_reference, prediction_actual)

    passed = True if threshold is None else bool(metric <= threshold)
    messages: Union[typing.List[TestMessage], None] = None

    if not passed:
        messages = [
            TestMessage(
                type=TestMessageType.ERROR,
                text=f"The prediction is drifting (metric is equal to {np.round(metric, 9)} "
                     f"and is above the test risk level {threshold}) ",
            )
        ]

    return TestResult(
        actual_slices_size=[len(actual_slice)],
        reference_slices_size=[len(reference_slice)],
        passed=bool(True if threshold is None else metric <= threshold),
        metric=metric,
        messages=messages,
    )
