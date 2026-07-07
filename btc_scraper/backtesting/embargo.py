import numpy as np

def embargo_train_indices(
    train_indices: np.ndarray,
    test_indices: np.ndarray,
    embargo_offset: int
) -> np.ndarray:
    """
    Utility function to apply embargo on train indices after the test split.
    Removes training indexes that fall within embargo_offset indices after the maximum test index.
    """
    if len(test_indices) == 0:
        return train_indices
        
    max_test_idx = np.max(test_indices)
    embargo_limit = max_test_idx + embargo_offset
    
    # Filter out train indices that fall after max_test_idx but before the embargo_limit
    embargoed = (train_indices > max_test_idx) & (train_indices <= embargo_limit)
    return train_indices[~embargoed]
