"""
Simple test script to verify object classification functionality
"""

import object_classifier

print("=" * 60)
print("Object Classification Test")
print("=" * 60)

# Test objects
test_objects = [
    "apple",
    "banana",
    "dog",
    "rose",
    "water",
    "elephant"
]

print("\nTesting classification for various objects:\n")

for obj in test_objects:
    print(f"Testing: {obj}")
    category = object_classifier.classify_object(obj)

    if category:
        display_name = object_classifier.get_category_display_name(category)
        level1 = object_classifier.LEVEL2_CATEGORIES.get(category)
        print(f"  [OK] Classified as: {category} ({display_name})")
        print(f"       Level 1: {level1}")
    else:
        print(f"  [FAIL] Could not classify")

    print()

print("=" * 60)
print("Test complete!")
print("=" * 60)
