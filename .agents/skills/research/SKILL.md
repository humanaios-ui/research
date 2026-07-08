```markdown
# research Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches the core development conventions and workflows used in the `research` TypeScript repository. You'll learn about file naming, import/export styles, commit patterns, and how to write and run tests. This guide is designed to help new contributors quickly adapt to the project's standards and streamline collaboration.

## Coding Conventions

### File Naming
- **Style:** snake_case
- **Example:**  
  ```plaintext
  data_processor.ts
  user_profile.test.ts
  ```

### Import Style
- **Relative imports** are preferred.
- **Example:**
  ```typescript
  import { processData } from './data_processor';
  ```

### Export Style
- **Named exports** are used instead of default exports.
- **Example:**
  ```typescript
  // In data_processor.ts
  export function processData(input: string): string {
    // implementation
  }
  ```

### Commit Patterns
- **Freeform messages** (no enforced type or prefix)
- **Average length:** ~22 characters
- **Example:**
  ```
  add initial data parser
  fix bug in user lookup
  update readme
  ```

## Workflows

### Adding a New Module
**Trigger:** When you need to introduce a new feature or utility.
**Command:** `/add-module`

1. Create a new `.ts` file using snake_case naming.
2. Implement your logic using named exports.
3. Import dependencies using relative paths.
4. Write a corresponding test file named `your_module.test.ts`.
5. Commit your changes with a concise, freeform message.

### Writing and Running Tests
**Trigger:** When you add or modify code that requires validation.
**Command:** `/run-tests`

1. Create a test file with the pattern `*.test.ts` (e.g., `data_processor.test.ts`).
2. Write your tests using the project's preferred (unknown) testing framework.
3. Run the tests using the project's test runner (consult project documentation if unsure).
4. Review test results and fix any failures before committing.

### Refactoring Existing Code
**Trigger:** When improving or restructuring code without changing its external behavior.
**Command:** `/refactor`

1. Identify the target module(s).
2. Apply changes, maintaining snake_case file naming and relative imports.
3. Update or add tests as needed.
4. Commit with a descriptive freeform message.

## Testing Patterns

- **Test files** use the pattern `*.test.ts`.
- **Testing framework** is not specified; check project documentation or existing test files for details.
- **Example test file:**
  ```typescript
  // data_processor.test.ts
  import { processData } from './data_processor';

  describe('processData', () => {
    it('should process input correctly', () => {
      expect(processData('input')).toBe('expectedOutput');
    });
  });
  ```

## Commands
| Command       | Purpose                                      |
|---------------|----------------------------------------------|
| /add-module   | Scaffold and add a new module                |
| /run-tests    | Run all test files matching `*.test.ts`      |
| /refactor     | Refactor existing code following conventions  |
```
