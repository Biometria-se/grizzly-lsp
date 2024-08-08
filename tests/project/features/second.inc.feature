Feature:
  Scenario: second
    Then log message "{$ bar $}=foo"
      | foo | bar |
      | bar | foo |
