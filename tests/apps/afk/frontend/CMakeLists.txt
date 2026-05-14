find_program(NODE_EXECUTABLE node)
if(NODE_EXECUTABLE)
    foreach(suite agent_messages speech_capture)
        add_test(NAME afk_frontend_${suite}
            COMMAND "${NODE_EXECUTABLE}"
                "${PROJECT_SOURCE_DIR}/apps/afk/frontend/tests/${suite}_test.mjs")
        set_tests_properties(afk_frontend_${suite} PROPERTIES TIMEOUT 30)
    endforeach()
else()
    message(STATUS "Node.js not found; AFK frontend tests are disabled")
endif()
