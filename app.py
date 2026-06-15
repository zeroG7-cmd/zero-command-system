from modules.logger import (
    get_total_tests,
    get_passed_tests,
    get_failed_tests
)



def show_dashboard():

    tests_completed = get_total_tests()
    passed = get_passed_testd()
    failed = get_failed_tests()



    
    print("=================================")
    print("ZERO COMMAND SYSTEM")
    print("=================================")

    print("\nR&D Summary\n")
    print(f"Tests Completed: {tests_completed}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    print("\nInventory\n")
    print(f"Motors: {}")
    print(f"ESCs: {}")
    

    print("\nCharacter\n")
    print(f"Level {} Engineer")
    print(f"INT: {}")
    print(f"ENG: {}")

    print("\nRecent Tests\n")
    print("CAMERA_TEST_001")
    print("PASS\n")
    print("LIDAR_TEST_001")
    print("FAIL")

def main():
    show_dashboard()


if __name__ == "__main__":
    main()
