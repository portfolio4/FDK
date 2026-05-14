include(FetchContent)

FetchContent_Declare(httplib
    GIT_REPOSITORY https://github.com/yhirose/cpp-httplib.git
    GIT_TAG v0.28.0
    GIT_SHALLOW TRUE)
FetchContent_MakeAvailable(httplib)
